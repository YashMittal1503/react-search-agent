"""The fallback engine: run a call across every (tier target x key) until one succeeds.

Attempt order for a tier:
  1. every *ready* key of every target, in tier order (round-robin within a provider);
  2. then keys that are cooling down, soonest recovery first;
  3. if nothing was attempted because everything is cooling, wait for the soonest key
     (up to ``max_wait_seconds``) and go again.
Trying a cooling key before a healthy key on the next tier only burns another 429.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping, TypeVar

from .config import PoolConfig, ProviderSpec, Target
from .errors import ErrorKind, classify_error, retry_after_seconds, status_code_of
from .keys import load_keys
from .pool import KeySlot, ProviderKeyPool

logger = logging.getLogger("llm_pool")
T = TypeVar("T")

try:  # optional telemetry
    import logfire as _logfire
except Exception:  # pragma: no cover
    _logfire = None


def _span(name: str, **attrs: Any):
    if _logfire is None:
        return contextlib.nullcontext(None)
    return _logfire.span(name, **attrs)


@dataclass
class Attempt:
    tier: str
    index: int            # position of the target in the tier
    target: Target
    spec: ProviderSpec
    slot: KeySlot
    pool: ProviderKeyPool

    @property
    def key(self) -> str:
        return self.slot.key

    def label(self) -> str:
        return f"{self.target.id} [{self.slot.masked_key}]"


class AllProvidersFailed(RuntimeError):
    def __init__(self, tier: str, errors: list[tuple[str, ErrorKind, str]]):
        self.tier = tier
        self.errors = errors
        detail = "; ".join(f"{t} -> {k.value}: {m[:160]}" for t, k, m in errors[-6:]) or "no provider has keys"
        super().__init__(f"All targets in tier {tier!r} failed ({len(errors)} attempts). {detail}")


class LLMRouter:
    def __init__(self, config: PoolConfig, env: Mapping[str, str] | None = None):
        self.config = config
        env = os.environ if env is None else env
        self.pools: dict[str, ProviderKeyPool] = {
            name: ProviderKeyPool(name, load_keys(spec.env_prefix, env)) for name, spec in config.providers.items()
        }
        self.stats: dict[str, dict[str, int]] = {}   # target id -> {ok, <error kind>...}

    # ── introspection ────────────────────────────────────────────────────
    def targets(self, tier: str) -> list[Target]:
        if tier not in self.config.tiers:
            raise KeyError(f"unknown tier {tier!r}; known: {sorted(self.config.tiers)}")
        return [t for t in self.config.tiers[tier] if self.pools.get(t.provider) and self.pools[t.provider].available]

    def key_counts(self) -> dict[str, int]:
        return {name: len(pool) for name, pool in self.pools.items()}

    def _record(self, target: Target, outcome: str) -> None:
        bucket = self.stats.setdefault(target.id, {})
        bucket[outcome] = bucket.get(outcome, 0) + 1

    # ── planning ─────────────────────────────────────────────────────────
    def plan(self, tier: str, skip: set[int] | None = None) -> tuple[list[Attempt], list[Attempt]]:
        ready, cooling = [], []
        now = time.time()
        for i, target in enumerate(self.config.tiers[tier]):
            if skip and i in skip:
                continue
            pool = self.pools.get(target.provider)
            if not pool or not pool.available or pool.model_disabled(target.model, now):
                continue
            spec = self.config.providers[target.provider]
            for slot in pool.rotation(target.model):
                a = Attempt(tier, i, target, spec, slot, pool)
                (ready if slot.is_ready(target.model, now) else cooling).append(a)
        cooling.sort(key=lambda a: a.slot.ready_at(a.target.model))
        return ready, cooling

    # ── error handling ───────────────────────────────────────────────────
    def handle_error(self, attempt: Attempt, err: BaseException, skip: set[int]) -> ErrorKind:
        kind = classify_error(err)
        t, pool, key = attempt.target, attempt.pool, attempt.key
        self._record(t, kind.value)
        if kind is ErrorKind.RATE_LIMIT:
            wait = retry_after_seconds(err)
            pool.cool_down(key, t.model, wait + 1 if wait is not None else pool.backoff_seconds(key, t.model), "rate limited")
        elif kind is ErrorKind.DAILY_LIMIT:
            wait = retry_after_seconds(err)
            pool.cool_down(key, t.model, max(wait or 0, 900.0) if wait else 3600.0, "daily limit")
        elif kind is ErrorKind.MODEL_UNAVAILABLE:
            pool.disable_model(t.model)
            skip.add(attempt.index)
        elif kind in (ErrorKind.REQUEST_TOO_LARGE, ErrorKind.BAD_OUTPUT, ErrorKind.INCOMPATIBLE):
            skip.add(attempt.index)       # this request won't work on this target; the key is fine
        elif kind is ErrorKind.AUTH:
            pool.cool_down(key, None, 3600.0, "auth failed")
        elif kind is ErrorKind.TRANSIENT:
            msg = str(err).lower()
            if status_code_of(err) in (502, 503, 529) or any(w in msg for w in ("overloaded", "high demand", "unavailable")):
                # the *model* is overloaded for everyone: other keys won't help, move to the next target
                skip.add(attempt.index)
                for slot in pool.slots:
                    pool.cool_down(slot.key, t.model, 30.0, "model overloaded")
            else:
                pool.cool_down(key, t.model, 8.0, "transient error")
        logger.warning("llm attempt failed: %s -> %s: %s", attempt.label(), kind.value, str(err)[:300])
        return kind

    # ── execution ────────────────────────────────────────────────────────
    async def _attempts(self, tier: str, skip: set[int], errors: list) -> AsyncIterator[Attempt]:
        """Yield attempts in order. Only ready keys are tried; if none are ready, wait for the
        soonest cooling key (up to ``max_wait_seconds``) and re-plan."""
        attempts = 0
        tried: set[tuple[int, str]] = set()
        for _round in range(4):
            ready, cooling = self.plan(tier, skip)
            fresh = [a for a in ready if (a.index, a.key) not in tried]
            if not fresh:
                if not cooling and not ready:
                    return
                pending = cooling or ready
                wait = min(a.slot.ready_at(a.target.model) for a in pending) - time.time()
                if wait > self.config.max_wait_seconds:
                    errors.append(("*", ErrorKind.RATE_LIMIT, f"all keys cooling; soonest in {wait:.0f}s"))
                    return
                if wait > 0:
                    logger.info("tier %s: every key is cooling; waiting %.1fs", tier, wait)
                    await asyncio.sleep(wait)
                tried.clear()
                continue
            for attempt in fresh:
                if attempt.index in skip:
                    continue
                if attempts >= self.config.max_attempts:
                    errors.append(("*", ErrorKind.FATAL, f"max_attempts={self.config.max_attempts} reached"))
                    return
                attempts += 1
                tried.add((attempt.index, attempt.key))
                yield attempt

    async def run(self, tier: str, fn: Callable[[Attempt], Awaitable[T]]) -> T:
        """Run ``fn(attempt)`` until one attempt succeeds."""
        errors: list[tuple[str, ErrorKind, str]] = []
        skip: set[int] = set()
        async for attempt in self._attempts(tier, skip, errors):
            with _span("LLM {provider}/{model}", provider=attempt.target.provider, model=attempt.target.model,
                       key_id=attempt.slot.masked_key, tier=tier):
                try:
                    result = await fn(attempt)
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001
                    kind = self.handle_error(attempt, err, skip)
                    errors.append((attempt.label(), kind, str(err)))
                    if kind is ErrorKind.FATAL:
                        raise
                    continue
            attempt.pool.mark_success(attempt.key, attempt.target.model)
            self._record(attempt.target, "ok")
            return result
        raise AllProvidersFailed(tier, errors)

    async def run_stream(self, tier: str, fn: Callable[[Attempt], AsyncIterator[T]]) -> AsyncIterator[T]:
        """Stream from the first attempt that yields. Failover only happens before the first item."""
        errors: list[tuple[str, ErrorKind, str]] = []
        skip: set[int] = set()
        async for attempt in self._attempts(tier, skip, errors):
            started = False
            try:
                async for item in fn(attempt):
                    started = True
                    yield item
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                if started:
                    self._record(attempt.target, "mid_stream_error")
                    raise
                kind = self.handle_error(attempt, err, skip)
                errors.append((attempt.label(), kind, str(err)))
                if kind is ErrorKind.FATAL:
                    raise
                continue
            attempt.pool.mark_success(attempt.key, attempt.target.model)
            self._record(attempt.target, "ok")
            return
        raise AllProvidersFailed(tier, errors)

    # ── raw OpenAI-SDK helpers (no LangChain needed) ─────────────────────
    def openai_client(self, attempt: Attempt):
        from openai import AsyncOpenAI

        cache_key = ("openai", attempt.spec.name)
        client = attempt.slot.cache.get(cache_key)
        if client is None:
            client = AsyncOpenAI(
                api_key=attempt.key, base_url=attempt.spec.base_url, max_retries=0,
                timeout=attempt.spec.timeout, default_headers=attempt.spec.headers or None,
            )
            attempt.slot.cache[cache_key] = client
        return client

    async def chat(self, tier: str, messages: list[dict], **kwargs: Any) -> Any:
        """Non-streaming chat completion. Returns the OpenAI response; ``response.model`` tells who answered."""
        async def call(a: Attempt):
            params = {**a.target.params, **kwargs}
            resp = await self.openai_client(a).chat.completions.create(model=a.target.model, messages=messages, **params)
            resp._llm_pool_target = a.target.id
            return resp

        return await self.run(tier, call)

    async def stream(self, tier: str, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]:
        """Stream text deltas."""
        async def call(a: Attempt):
            params = {**a.target.params, **kwargs}
            stream = await self.openai_client(a).chat.completions.create(
                model=a.target.model, messages=messages, stream=True, **params,
            )
            async for chunk in stream:
                if chunk.choices and getattr(chunk.choices[0].delta, "content", None):
                    yield chunk.choices[0].delta.content

        async for text in self.run_stream(tier, call):
            yield text
