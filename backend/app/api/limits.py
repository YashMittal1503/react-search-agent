"""Tiny per-IP daily limiter (in-memory; swap for Redis when hosting multiple instances)."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

# (ip, bucket, UTC day) -> requests so far. Resets on restart, which is acceptable for a free demo.
_counts: dict[tuple[str, str, str], int] = defaultdict(int)


def client_ip(request: Request) -> str:
    """Caller's IP: the first ``X-Forwarded-For`` hop when behind a proxy, else the socket address."""
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")) or "unknown"


def check(request: Request, bucket: str, per_day: int) -> int:
    """Count one request against ``bucket`` for the caller's IP today.

    Args:
        bucket: separate limits share one counter table, e.g. ``"chat"`` and ``"deep research"``.
        per_day: allowed requests per IP per UTC day; ``0`` or less disables the limit.

    Returns:
        Requests remaining today.

    Raises:
        HTTPException: 429 when the limit is already reached.
    """
    if per_day <= 0:
        return 1_000_000
    day = time.strftime("%Y-%m-%d", time.gmtime())
    key = (client_ip(request), bucket, day)
    if _counts[key] >= per_day:
        raise HTTPException(429, detail=f"Daily limit reached for {bucket} ({per_day}/day). This demo runs on free model tiers.")
    _counts[key] += 1
    # drop old days
    for k in [k for k in _counts if k[2] != day]:
        _counts.pop(k, None)
    return per_day - _counts[key]
