"""Load API keys from the environment.

Conventions (all optional, all merged, order preserved, duplicates removed):
    <PREFIX>_API_KEYS=key1,key2,key3      comma-separated list (tried first)
    <PREFIX>_API_KEY=key                  primary key
    <PREFIX>_API_KEY_2 ... _API_KEY_N     any number of numbered keys (gaps allowed)
"""

from __future__ import annotations

import os
import re
from typing import Mapping


def mask_key(key: str) -> str:
    """Mask a secret for logs and traces, e.g. ``gsk_...3a4f``."""
    if not key:
        return "<none>"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def _clean(value: str | None) -> str:
    v = (value or "").strip().strip('"').strip("'")
    # Ignore placeholders copied from .env.example files.
    if not v or "your_" in v.lower() or v.lower() in {"changeme", "xxx", "none", "null"}:
        return ""
    return v


def load_keys(prefix: str, env: Mapping[str, str] | None = None) -> list[str]:
    """Collect every key configured for ``prefix`` (e.g. ``"GROQ"``)."""
    env = os.environ if env is None else env
    prefix = prefix.upper()
    keys: list[str] = []

    for part in (env.get(f"{prefix}_API_KEYS") or "").split(","):
        if _clean(part):
            keys.append(_clean(part))

    numbered: list[tuple[int, str]] = []
    pattern = re.compile(rf"^{re.escape(prefix)}_API_KEY(?:_(\d+))?$", re.IGNORECASE)
    for name, value in env.items():
        m = pattern.match(name)
        if m and _clean(value):
            numbered.append((int(m.group(1) or 1), _clean(value)))
    keys.extend(v for _, v in sorted(numbered))

    return list(dict.fromkeys(keys))
