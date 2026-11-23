"""Small on-disk TTL cache for searches and fetches (saves free-tier quota)."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

import diskcache

from ..settings import get_settings


@lru_cache
def _cache() -> diskcache.Cache:
    return diskcache.Cache(get_settings().cache_dir, size_limit=512 * 1024 * 1024)


def make_key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def get(key: str) -> Any:
    try:
        return _cache().get(key)
    except Exception:
        return None


def set(key: str, value: Any, ttl: float) -> None:  # noqa: A001
    try:
        _cache().set(key, value, expire=ttl)
    except Exception:
        pass
