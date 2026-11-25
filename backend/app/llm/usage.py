"""Token accounting per run: which provider/model was called, how often, and how many tokens it used.

:class:`TokenTracker` is a LangChain callback handler. Put it in a run's config (``{"callbacks": [tracker]}``) and
LangChain hands it every chat-model call made anywhere below that run: the router, the quick ReAct agent, the deep
agent and its subagents, the writer, follow-ups, or the eval judge. It records one :class:`CallUsage` per
successful call and can summarise them by model and by graph step.

Where the numbers come from:

* ``provider`` / ``model``: ``llm_pool`` tags every response with ``response_metadata["llm_pool_target"]``
  (``"groq:openai/gpt-oss-120b"``), i.e. the target that actually answered after any failover.
* tokens: the provider's own ``usage`` block, which LangChain exposes as ``AIMessage.usage_metadata``
  (input, output, cached input, reasoning).
* streamed calls (the writer) come back without a usage block, because ``llm_pool`` turns off
  ``stream_usage`` (not every OpenAI-compatible provider accepts it). For those, tokens are *estimated* at ~4
  characters per token and the record is flagged ``estimated=True``, so reports can say how much is a guess.

Failed attempts inside the key pool (429s, timeouts) are retried inside one LangChain call, so they don't appear
here. Only the attempt that produced the answer is counted.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

CHARS_PER_TOKEN = 4   # rough average for English text; only used when a provider reports no usage


@dataclass
class CallUsage:
    """Token use of one successful chat-model call."""

    provider: str
    model: str
    step: str                 # graph node that made the call: route, quick_research, deep_research, synthesize, ...
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0    # input tokens served from the provider's prompt cache (don't count on Groq limits)
    reasoning_tokens: int = 0 # hidden "thinking" tokens, already included in output_tokens
    estimated: bool = False   # True when the provider sent no usage and the numbers are a character-count guess

    @property
    def total_tokens(self) -> int:
        """Input + output tokens."""
        return self.input_tokens + self.output_tokens


def _chars(value: Any) -> int:
    """Approximate character count of message content (a string or a list of content blocks)."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_chars(v.get("text", "") if isinstance(v, dict) else v) for v in value)
    return len(str(value or ""))


def _step_from(metadata: dict[str, Any] | None) -> str:
    """Which top-level graph node a call belongs to.

    LangGraph puts ``checkpoint_ns`` ("deep_research:<task id>|model:<id>...") and ``langgraph_node`` into the
    callback metadata. The first segment of the namespace is the outer node, even for calls made by an agent or
    subagent running inside it; top-level nodes have an empty namespace, so their own node name is used.
    """
    md = metadata or {}
    ns = str(md.get("checkpoint_ns") or "")
    if ns:
        return ns.split("|", 1)[0].split(":", 1)[0]
    return str(md.get("langgraph_node") or md.get("usage_step") or "other")


class TokenTracker(BaseCallbackHandler):
    """Collects :class:`CallUsage` records for one run (one chat turn, or one eval item's judge calls).

    Thread-safe and cheap, so it runs inline in the event loop (``run_inline``) instead of in a thread pool.
    """

    run_inline = True

    def __init__(self, default_step: str = "other") -> None:
        super().__init__()
        self.default_step = default_step
        self.calls: list[CallUsage] = []
        self._pending: dict[UUID, dict[str, Any]] = {}   # run_id -> prompt size + step, until the call ends
        self._lock = threading.Lock()

    # ── LangChain callback hooks ───────────────────────────────────────────
    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], *, run_id: UUID,
                            parent_run_id: UUID | None = None, tags: list[str] | None = None,
                            metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Remember the prompt size (for estimates) and the graph step, keyed by this call's run id."""
        prompt_chars = sum(_chars(getattr(m, "content", m)) for batch in messages for m in batch)
        step = _step_from(metadata)
        with self._lock:
            self._pending[run_id] = {"prompt_chars": prompt_chars, "step": self.default_step if step == "other" else step}

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any) -> None:
        """Record the finished call's tokens (reported by the provider, or estimated for streamed calls)."""
        with self._lock:
            pending = self._pending.pop(run_id, {"prompt_chars": 0, "step": self.default_step})
        gens = [g for batch in response.generations for g in batch]
        if not gens:
            return
        msg = getattr(gens[0], "message", None)
        meta = getattr(msg, "response_metadata", None) or {}
        target = meta.get("llm_pool_target") or (response.llm_output or {}).get("llm_pool_target") or "unknown:unknown"
        provider, _, model = str(target).partition(":")
        usage = getattr(msg, "usage_metadata", None)
        if usage and (usage.get("input_tokens") or usage.get("output_tokens")):
            rec = CallUsage(
                provider, model, pending["step"],
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cached_tokens=int((usage.get("input_token_details") or {}).get("cache_read") or 0),
                reasoning_tokens=int((usage.get("output_token_details") or {}).get("reasoning") or 0),
            )
        else:
            text = "".join(getattr(g, "text", "") or "" for g in gens)
            rec = CallUsage(provider, model, pending["step"],
                            input_tokens=pending["prompt_chars"] // CHARS_PER_TOKEN,
                            output_tokens=len(text) // CHARS_PER_TOKEN, estimated=True)
        with self._lock:
            self.calls.append(rec)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        """A call that failed on every key/tier used no tokens we can measure; just forget it."""
        with self._lock:
            self._pending.pop(run_id, None)

    # ── reporting ──────────────────────────────────────────────────────────
    def records(self) -> list[dict[str, Any]]:
        """Every call as a plain dict (for JSON reports)."""
        with self._lock:
            return [{**asdict(c), "total_tokens": c.total_tokens} for c in self.calls]

    def summary(self) -> dict[str, Any]:
        """Totals plus breakdowns by (provider, model) and by graph step. See :func:`summarize_calls`."""
        with self._lock:
            calls = list(self.calls)
        return summarize_calls(calls)


def _empty_totals() -> dict[str, int]:
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "reasoning_tokens": 0,
            "total_tokens": 0, "estimated_calls": 0}


def summarize_calls(calls: list[CallUsage]) -> dict[str, Any]:
    """Aggregate call records.

    Returns:
        ``{"calls", "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens", "total_tokens",
        "estimated_calls", "by_model": [{"provider", "model", ...same counters}], "by_step": {step: total_tokens}}``.
        ``by_model`` is sorted by total tokens, largest first.
    """
    totals = _empty_totals()
    by_model: dict[tuple[str, str], dict[str, int]] = defaultdict(_empty_totals)
    by_step: dict[str, int] = defaultdict(int)
    for c in calls:
        for bucket in (totals, by_model[(c.provider, c.model)]):
            bucket["calls"] += 1
            bucket["input_tokens"] += c.input_tokens
            bucket["output_tokens"] += c.output_tokens
            bucket["cached_tokens"] += c.cached_tokens
            bucket["reasoning_tokens"] += c.reasoning_tokens
            bucket["total_tokens"] += c.total_tokens
            bucket["estimated_calls"] += int(c.estimated)
        by_step[c.step] += c.total_tokens
    models = [{"provider": p, "model": m, **v} for (p, m), v in by_model.items()]
    models.sort(key=lambda r: r["total_tokens"], reverse=True)
    return {**totals, "by_model": models, "by_step": dict(by_step)}


def merge_summaries(summaries: list[dict[str, Any] | None]) -> dict[str, Any]:
    """Add several :func:`summarize_calls` results together (turns of a conversation, items of an eval suite)."""
    totals = _empty_totals()
    by_model: dict[tuple[str, str], dict[str, int]] = defaultdict(_empty_totals)
    by_step: dict[str, int] = defaultdict(int)
    for s in summaries:
        if not s:
            continue
        for k in totals:
            totals[k] += int(s.get(k) or 0)
        for row in s.get("by_model", []):
            bucket = by_model[(row["provider"], row["model"])]
            for k in bucket:
                bucket[k] += int(row.get(k) or 0)
        for step, n in (s.get("by_step") or {}).items():
            by_step[step] += int(n)
    models = [{"provider": p, "model": m, **v} for (p, m), v in by_model.items()]
    models.sort(key=lambda r: r["total_tokens"], reverse=True)
    return {**totals, "by_model": models, "by_step": dict(by_step)}
