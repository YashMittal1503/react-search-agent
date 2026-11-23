"""Small on-disk TTL cache for searches and fetches (saves free-tier quota and makes reruns fast).

Backed by ``diskcache`` (SQLite under ``data/cache``, capped at 512 MB). Every call swallows cache errors: a broken
cache must never break a chat turn, it just means a cache miss.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

import diskcache

from ..settings import get_settings


@lru_cache
def _cache() -> diskcache.Cache:
    """The process-wide cache (opened lazily on first use)."""
    return diskcache.Cache(get_settings().cache_dir, size_limit=512 * 1024 * 1024)


def make_key(*parts: Any) -> str:
    """Stable key from any JSON-able parts, e.g. ``make_key("search", query, n, recency_days, news)``."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def get(key: str) -> Any:
    """Cached value, or ``None`` when missing, expired or the cache is unavailable."""
    try:
        return _cache().get(key)
    except Exception:
        return None


def set(key: str, value: Any, ttl: float) -> None:  # noqa: A001 - mirrors the cache API on purpose
    """Store ``value`` for ``ttl`` seconds (best effort)."""
    try:
        _cache().set(key, value, expire=ttl)
    except Exception:
        pass
