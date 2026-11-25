"""Classify provider errors and work out how long to back off.

The classification decides what the router does next:

    RATE_LIMIT         429 / RPM / TPM       -> cool down this (key, model), try the next attempt
    DAILY_LIMIT        RPD / TPD / quota     -> long cool down for this (key, model)
    MODEL_UNAVAILABLE  404 / 410 / retired   -> disable the model on this provider (key is fine)
    REQUEST_TOO_LARGE  413 / context length  -> skip this target for this request only
    BAD_OUTPUT         malformed tool call   -> skip this target for this request only
    INCOMPATIBLE       other 400 / 422       -> skip this target for this request only
    AUTH               401 / 403             -> disable the key for a while
    TRANSIENT          5xx / timeout / net   -> short cool down, try the next attempt
    FATAL              programming errors    -> raise immediately
"""

from __future__ import annotations

import re
from enum import Enum


class ErrorKind(str, Enum):
    """What kind of failure an exception is; see the module docstring for the router's reaction to each."""

    RATE_LIMIT = "rate_limit"
    DAILY_LIMIT = "daily_limit"
    MODEL_UNAVAILABLE = "model_unavailable"
    REQUEST_TOO_LARGE = "request_too_large"
    BAD_OUTPUT = "bad_output"
    INCOMPATIBLE = "incompatible"
    AUTH = "auth"
    TRANSIENT = "transient"
    FATAL = "fatal"


# Word-boundary patterns: a bare substring like "rpm" also matches URLs such as ".../rpm-docs".
_RATE_RE = re.compile(r"rate[ _-]?limit|too many requests|per[ _-]?minute|\b[rt]pm\b")
_DAILY_RE = re.compile(r"per[ _-]?day|\b[rt]pd\b|daily")
_MINUTE_RE = re.compile(r"per[ _-]?minute|\b[rt]pm\b")
# Gemini says "exceeded your current quota" for per-minute *and* per-day limits; its quotaId tells them apart.
_QUOTA_TERMS = ("quota exceeded", "resource_exhausted", "exceeded your current quota")
_UNAVAILABLE_TERMS = (
    "model_not_found", "decommissioned", "does not exist", "no longer supported", "unknown model",
    "end of life", "not found for api version", "is not supported for", "no endpoints found",
)
_TOO_LARGE_TERMS = ("context_length", "context length", "maximum context", "too large", "too many tokens", "request entity too large", "reduce the length")
_BAD_OUTPUT_TERMS = (
    "tool_use_failed", "failed to call a function", "failed_generation", "invalid tool call", "output_parse_failed",
    "tool call validation failed", "which was not in request.tools",
)
_TRANSIENT_TERMS = ("timeout", "timed out", "overloaded", "service unavailable", "capacity", "connection", "temporarily", "bad gateway", "internal server error")

_NETWORK_ERROR_NAMES = {
    "APITimeoutError", "APIConnectionError", "TimeoutException", "ConnectTimeout", "ReadTimeout",
    "ConnectError", "ReadError", "RemoteProtocolError", "NetworkError", "PoolTimeout", "WriteTimeout",
}


def status_code_of(err: BaseException) -> int | None:
    """HTTP status of an SDK/httpx error (``err.status_code`` or ``err.response.status_code``), else ``None``."""
    code = getattr(err, "status_code", None)
    if code is None:
        resp = getattr(err, "response", None)
        code = getattr(resp, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def classify_error(err: BaseException) -> ErrorKind:
    """Map any exception from a provider call to an :class:`ErrorKind`.

    Order matters: status codes are the most reliable signal, then message wording (providers phrase the same
    limit very differently), then exception type names for network errors. Anything unrecognised is FATAL, so
    real bugs surface instead of being retried forever.
    """
    status = status_code_of(err)
    msg = str(err).lower()
    name = type(err).__name__
    # wrappers (e.g. langchain_openai.OpenAITimeoutError) subclass the SDK errors: match on the whole MRO
    names = {c.__name__ for c in type(err).__mro__}

    # Before the rate-limit check: Groq's 413 says "Request too large ... tokens per minute (TPM)". No key can
    # serve that request, so it must skip the target, not cool every key down one by one.
    if status == 413 or (status != 429 and any(t in msg for t in _TOO_LARGE_TERMS)):
        return ErrorKind.REQUEST_TOO_LARGE
    if status == 429 or "RateLimitError" in names:
        return _limit_kind(err, msg)
    if status in (404, 410):
        return ErrorKind.MODEL_UNAVAILABLE
    if _RATE_RE.search(msg) or any(t in msg for t in _QUOTA_TERMS):
        return _limit_kind(err, msg)
    if any(t in msg for t in _UNAVAILABLE_TERMS):
        return ErrorKind.MODEL_UNAVAILABLE
    if any(t in msg for t in _BAD_OUTPUT_TERMS):
        return ErrorKind.BAD_OUTPUT
    if status in (401, 403):
        return ErrorKind.AUTH
    if status == 402:  # payment required (e.g. OpenRouter negative balance)
        return ErrorKind.DAILY_LIMIT
    if status in (400, 422):
        return ErrorKind.INCOMPATIBLE
    if (status is not None and status >= 500) or status == 408:
        return ErrorKind.TRANSIENT
    if names & _NETWORK_ERROR_NAMES or isinstance(err, (TimeoutError, ConnectionError)):
        return ErrorKind.TRANSIENT
    if status is None and any(t in msg for t in _TRANSIENT_TERMS) and name.endswith("Error") and "API" in name:
        return ErrorKind.TRANSIENT
    return ErrorKind.FATAL


def _limit_kind(err: BaseException, msg: str) -> ErrorKind:
    """Per-minute or per-day limit? Explicit wording wins; a bare "quota exceeded" is daily unless the
    provider says it resets within two minutes."""
    if _DAILY_RE.search(msg):
        return ErrorKind.DAILY_LIMIT
    if _MINUTE_RE.search(msg):
        return ErrorKind.RATE_LIMIT
    if any(t in msg for t in _QUOTA_TERMS):
        wait = retry_after_seconds(err)
        return ErrorKind.RATE_LIMIT if wait is not None and wait <= 120 else ErrorKind.DAILY_LIMIT
    return ErrorKind.RATE_LIMIT


# "Limit 8000" in Groq's too-large errors.
_LIMIT_RE = re.compile(r"\blimit[:\s]+(\d{3,})", re.IGNORECASE)


def token_limit_of(err: BaseException) -> int | None:
    """The token ceiling a too-large error names, e.g. Groq's "(TPM): Limit 8000, Requested 14210"."""
    m = _LIMIT_RE.search(str(err))
    return int(m.group(1)) if m else None


# Durations like "1h2m3.5s" / "500ms" (each part optional; "m" not followed by "s" means minutes).
_DURATION_RE = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$")


def parse_duration(text: str) -> float | None:
    """Parse ``"7.66s"``, ``"2m59.5s"``, ``"1h2m"``, ``"500ms"`` or ``"12"`` into seconds."""
    if not text:
        return None
    text = text.strip().lower()
    try:
        return float(text)
    except ValueError:
        pass
    m = _DURATION_RE.match(text)
    if not m or not any(m.groups()):
        return None
    h, mi, s, ms = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


# "Please try again in 7m4.2s" (Groq/OpenAI) and "retryDelay": "31s" (Gemini) inside error messages.
_TRY_AGAIN_RE = re.compile(r"(?:try again in|retry after|retry in|please retry in)\s+([\d\.hms]+)", re.IGNORECASE)
_RETRY_DELAY_RE = re.compile(r"retrydelay['\"]?\s*[:=]\s*['\"]?([\d\.]+)s", re.IGNORECASE)


def retry_after_seconds(err: BaseException) -> float | None:
    """Best-effort wait time from headers or the error message.

    Headers win (``Retry-After``, ``x-ratelimit-reset-*``; the smallest when several are present, since the first
    reset frees capacity); otherwise the "try again in ..." / ``retryDelay`` text. ``None`` when nothing is given,
    and the caller falls back to exponential backoff.
    """
    resp = getattr(err, "response", None)
    headers = getattr(resp, "headers", None) or {}
    candidates: list[float] = []
    for h in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens", "x-ratelimit-reset"):
        try:
            value = headers.get(h)
        except Exception:
            value = None
        if value:
            d = parse_duration(str(value))
            if d is not None:
                candidates.append(d)
    if candidates:
        return max(0.0, min(candidates) if len(candidates) > 1 else candidates[0])

    msg = str(err)
    for rx in (_TRY_AGAIN_RE, _RETRY_DELAY_RE):
        m = rx.search(msg)
        if m:
            d = parse_duration(m.group(1).rstrip("."))
            if d is not None:
                return d
    return None
