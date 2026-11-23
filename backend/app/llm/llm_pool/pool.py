"""Round-robin key pool with per-(key, model) cooldowns.

All state changes are synchronous (no ``await`` inside), so a pool is safe to share
between coroutines on one event loop. State is per process: with several workers
each keeps its own cooldowns, which is fine for free tiers (a 429 just re-cools).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .keys import mask_key

logger = logging.getLogger("llm_pool")


@dataclass
class KeySlot:
    key: str
    masked_key: str
    cooldown_until: float = 0.0                       # key-wide (auth problems, provider-wide limits)
    model_cooldowns: dict[str, float] = field(default_factory=dict)  # free tiers limit each model separately
    failures: dict[str, int] = field(default_factory=dict)          # consecutive failures per model
    cache: dict[Any, Any] = field(default_factory=dict)             # clients built for this key

    def ready_at(self, model: str | None = None) -> float:
        return max(self.cooldown_until, self.model_cooldowns.get(model, 0.0) if model else 0.0)

    def is_ready(self, model: str | None = None, now: float | None = None) -> bool:
        return self.ready_at(model) <= (time.time() if now is None else now)


class ProviderKeyPool:
    """All keys for one provider."""

    def __init__(self, provider: str, keys: list[str]):
        self.provider = provider
        self.slots: list[KeySlot] = [KeySlot(key=k, masked_key=mask_key(k)) for k in dict.fromkeys(keys) if k]
        self._index: dict[str | None, int] = {}   # round-robin position per model
        self.disabled_models: dict[str, float] = {}   # model -> disabled until (404 / retired)

    def __len__(self) -> int:
        return len(self.slots)

    @property
    def available(self) -> bool:
        return bool(self.slots)

    def model_disabled(self, model: str, now: float | None = None) -> bool:
        return self.disabled_models.get(model, 0.0) > (time.time() if now is None else now)

    def rotation(self, model: str | None = None) -> list[KeySlot]:
        """Keys in round-robin order: ready keys first, then cooling keys (soonest first)."""
        if not self.slots:
            return []
        n = len(self.slots)
        start = self._index.get(model, 0)
        ordered = [self.slots[(start + i) % n] for i in range(n)]
        self._index[model] = (start + 1) % n
        now = time.time()
        ready = [s for s in ordered if s.is_ready(model, now)]
        cooling = sorted((s for s in ordered if not s.is_ready(model, now)), key=lambda s: s.ready_at(model))
        return ready + cooling

    def _slot(self, key: str) -> KeySlot | None:
        return next((s for s in self.slots if s.key == key), None)

    def cool_down(self, key: str, model: str | None, seconds: float, reason: str = "rate_limit") -> float:
        slot = self._slot(key)
        if slot is None:
            return 0.0
        until = time.time() + seconds
        if model:
            slot.model_cooldowns[model] = max(slot.model_cooldowns.get(model, 0.0), until)
            slot.failures[model] = slot.failures.get(model, 0) + 1
        else:
            slot.cooldown_until = max(slot.cooldown_until, until)
        logger.warning(
            "[%s] key %s %s%s -> cooling %.0fs",
            self.provider, slot.masked_key, reason, f" on {model}" if model else "", seconds,
        )
        return seconds

    def backoff_seconds(self, key: str, model: str, base: float = 20.0, cap: float = 300.0) -> float:
        """Exponential backoff with jitter, used when the provider gives no reset time."""
        slot = self._slot(key)
        n = (slot.failures.get(model, 0) if slot else 0)
        return min(cap, base * (2 ** n)) * random.uniform(0.8, 1.2)

    def disable_model(self, model: str, seconds: float = 3600.0) -> None:
        self.disabled_models[model] = time.time() + seconds
        logger.warning("[%s] model %s unavailable -> disabled for %.0fs", self.provider, model, seconds)

    def mark_success(self, key: str, model: str | None = None) -> None:
        slot = self._slot(key)
        if slot and model:
            slot.failures.pop(model, None)
