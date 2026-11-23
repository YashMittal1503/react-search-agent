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
    RATE_LIMIT = "rate_limit"
    DAILY_LIMIT = "daily_limit"
    MODEL_UNAVAILABLE = "model_unavailable"
    REQUEST_TOO_LARGE = "request_too_large"
    BAD_OUTPUT = "bad_output"
    INCOMPATIBLE = "incompatible"
    AUTH = "auth"
    TRANSIENT = "transient"
    FATAL = "fatal"


_DAILY_TERMS = ("per day", "rpd", "tpd", "daily", "quota exceeded", "resource_exhausted", "exceeded your current quota")
_RATE_TERMS = ("rate limit", "rate_limit", "too many requests", "tokens per minute", "tpm", "requests per minute", "rpm")
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
    code = getattr(err, "status_code", None)
    if code is None:
        resp = getattr(err, "response", None)
        code = getattr(resp, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def classify_error(err: BaseException) -> ErrorKind:
    status = status_code_of(err)
    msg = str(err).lower()
    name = type(err).__name__
    # wrappers (e.g. langchain_openai.OpenAITimeoutError) subclass the SDK errors: match on the whole MRO
    names = {c.__name__ for c in type(err).__mro__}

    if status == 429 or "RateLimitError" in names or any(t in msg for t in _RATE_TERMS):
        return ErrorKind.DAILY_LIMIT if any(t in msg for t in _DAILY_TERMS) else ErrorKind.RATE_LIMIT
    if status in (404, 410) or any(t in msg for t in _UNAVAILABLE_TERMS):
        return ErrorKind.MODEL_UNAVAILABLE
    if status == 413 or any(t in msg for t in _TOO_LARGE_TERMS):
        return ErrorKind.REQUEST_TOO_LARGE
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


_TRY_AGAIN_RE = re.compile(r"(?:try again in|retry after|retry in|please retry in)\s+([\d\.hms]+)", re.IGNORECASE)
_RETRY_DELAY_RE = re.compile(r"retrydelay['\"]?\s*[:=]\s*['\"]?([\d\.]+)s", re.IGNORECASE)


def retry_after_seconds(err: BaseException) -> float | None:
    """Best-effort wait time from headers or the error message."""
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
