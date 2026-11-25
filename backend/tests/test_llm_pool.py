"""Offline tests for llm_pool (no network). Run: pytest tests/test_llm_pool.py"""

import asyncio
import time
from datetime import UTC

import pytest

from app.llm.llm_pool import (
    ErrorKind,
    LLMRouter,
    PoolConfig,
    classify_error,
    load_keys,
    parse_duration,
    retry_after_seconds,
)
from app.llm.llm_pool.router import AllProvidersFailed


class FakeErr(Exception):
    def __init__(self, msg, status=None, headers=None):
        super().__init__(msg)
        self.status_code = status
        self.response = type("R", (), {"headers": headers or {}, "status_code": status})()


ENV = {"GROQ_API_KEY": "gsk_aaaa1111", "GROQ_API_KEY_2": "gsk_bbbb2222", "GEMINI_API_KEYS": "AIza_cccc3333",
       "MISTRAL_API_KEY": "your_mistral_key"}
CFG = {"max_wait_seconds": 0.5, "tiers": {"t": ["groq:m1", "groq:m2", "gemini:g1", "mistral:x"]}}


def router():
    return LLMRouter(PoolConfig.from_dict(CFG), env=ENV)


def test_load_keys_merges_numbered_and_list_and_skips_placeholders():
    env = {"X_API_KEYS": "a1234567,b1234567", "X_API_KEY": "c1234567", "X_API_KEY_7": "d1234567", "X_API_KEY_2": "a1234567"}
    assert load_keys("X", env) == ["a1234567", "b1234567", "c1234567", "d1234567"]
    assert load_keys("MISTRAL", ENV) == []


def test_parse_duration():
    assert parse_duration("7.66s") == pytest.approx(7.66)
    assert parse_duration("2m59.5s") == pytest.approx(179.5)
    assert parse_duration("1h2m") == pytest.approx(3720)
    assert parse_duration("500ms") == pytest.approx(0.5)
    assert parse_duration("12") == 12


def test_classify():
    assert classify_error(FakeErr("Rate limit reached ... tokens per minute", 429)) is ErrorKind.RATE_LIMIT
    assert classify_error(FakeErr("Rate limit reached on tokens per day (TPD)", 429)) is ErrorKind.DAILY_LIMIT
    assert classify_error(FakeErr("model has been decommissioned", 400)) is ErrorKind.MODEL_UNAVAILABLE
    assert classify_error(FakeErr("tool_use_failed", 400)) is ErrorKind.BAD_OUTPUT
    assert classify_error(FakeErr("context_length_exceeded", 400)) is ErrorKind.REQUEST_TOO_LARGE
    assert classify_error(FakeErr("bad", 503)) is ErrorKind.TRANSIENT
    assert classify_error(FakeErr("nope", 401)) is ErrorKind.AUTH
    assert classify_error(ValueError("bug")) is ErrorKind.FATAL


def test_retry_after_from_header_and_message():
    assert retry_after_seconds(FakeErr("x", 429, {"retry-after": "3"})) == 3
    assert retry_after_seconds(FakeErr("Please try again in 1m2.5s.", 429)) == pytest.approx(62.5)


def test_targets_skip_providers_without_keys():
    assert [t.id for t in router().targets("t")] == ["groq:m1", "groq:m2", "gemini:g1"]


def test_round_robin_rotation():
    r = router()
    first = [a.key for a in r.plan("t")[0] if a.target.model == "m1"]
    second = [a.key for a in r.plan("t")[0] if a.target.model == "m1"]
    assert first[0] != second[0]


def test_rate_limit_is_per_key_and_model_and_fails_over():
    r = router()
    calls = []

    async def fn(a):
        calls.append(a.label())
        if a.target.provider == "groq":
            raise FakeErr("rate limit", 429, {"retry-after": "30"})
        return a.target.id

    assert asyncio.run(r.run("t", fn)) == "gemini:g1"
    groq = r.pools["groq"]
    assert all(s.model_cooldowns["m1"] > time.time() for s in groq.slots)
    assert all(s.cooldown_until == 0 for s in groq.slots)   # key itself still fine
    assert len(calls) == 5                                   # 2 keys x 2 groq models, then gemini


def test_model_unavailable_disables_model_not_key():
    r = router()

    async def fn(a):
        if a.target.model == "m1":
            raise FakeErr("model_not_found", 404)
        return a.target.id

    assert asyncio.run(r.run("t", fn)) == "groq:m2"
    assert r.pools["groq"].model_disabled("m1")


def test_fatal_raises_immediately():
    async def fn(a):
        raise ValueError("bug")

    with pytest.raises(ValueError):
        asyncio.run(router().run("t", fn))


def test_all_cooling_beyond_max_wait_raises():
    r = router()
    for pool in r.pools.values():
        for s in pool.slots:
            s.cooldown_until = time.time() + 999

    async def fn(a):
        return "never"

    with pytest.raises(AllProvidersFailed):
        asyncio.run(r.run("t", fn))


def test_waits_for_short_cooldown():
    r = router()
    for pool in r.pools.values():
        for s in pool.slots:
            s.cooldown_until = time.time() + 0.2

    async def fn(a):
        return a.target.id

    assert asyncio.run(r.run("t", fn)) == "groq:m1"


def test_stream_fails_over_before_first_token():
    r = router()

    def fn(a):
        async def gen():
            if a.target.provider == "groq":
                raise FakeErr("overloaded", 503)
            yield "hi"
        return gen()

    async def collect():
        return [x async for x in r.run_stream("t", fn)]

    assert asyncio.run(collect()) == ["hi"]


def test_overloaded_model_skips_remaining_keys():
    r = router()
    calls = []

    async def fn(a):
        calls.append(a.label())
        if a.target.model == "m1":
            raise FakeErr("This model is currently experiencing high demand", 503)
        return a.target.id

    assert asyncio.run(r.run("t", fn)) == "groq:m2"
    assert sum("groq:m1" in c for c in calls) == 1    # second key not wasted on an overloaded model


def test_wrapped_timeout_is_transient():
    class APITimeoutError(Exception):
        pass

    class OpenAITimeoutError(APITimeoutError):
        pass

    assert classify_error(OpenAITimeoutError("Request timed out.")) is ErrorKind.TRANSIENT
    assert classify_error(FakeErr("Tool call validation failed: attempted to call tool 'x' which was not in request.tools", 400)) is ErrorKind.BAD_OUTPUT


# ── phase 1: classification fixes, request ceilings, shared quotas, reset times, tier fallbacks ──────

def test_groq_413_tpm_is_too_large_not_rate_limit():
    err = FakeErr("Request too large for model openai/gpt-oss-120b on tokens per minute (TPM): "
                  "Limit 8000, Requested 14210, please reduce your message size and try again.", 413)
    assert classify_error(err) is ErrorKind.REQUEST_TOO_LARGE
    from app.llm.llm_pool.errors import token_limit_of
    assert token_limit_of(err) == 8000


def test_rate_terms_need_word_boundaries():
    assert classify_error(FakeErr("model gone, see https://docs.example/rpm-docs", 404)) is ErrorKind.MODEL_UNAVAILABLE
    assert classify_error(FakeErr("unknown model 'tpmx-large'", 400)) is ErrorKind.MODEL_UNAVAILABLE


def test_gemini_quota_minute_vs_day():
    minute = FakeErr("You exceeded your current quota. quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier", 429)
    day = FakeErr("You exceeded your current quota. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier", 429)
    short = FakeErr("RESOURCE_EXHAUSTED: quota exceeded. 'retryDelay': '20s'", 429)
    bare = FakeErr("RESOURCE_EXHAUSTED: quota exceeded", 429)
    assert classify_error(minute) is ErrorKind.RATE_LIMIT
    assert classify_error(day) is ErrorKind.DAILY_LIMIT
    assert classify_error(short) is ErrorKind.RATE_LIMIT
    assert classify_error(bare) is ErrorKind.DAILY_LIMIT


def test_oversized_request_skips_target_without_calling_it():
    cfg = {**CFG, "providers": {"groq": {"max_request_tokens": 100}}}
    r = LLMRouter(PoolConfig.from_dict(cfg), env=ENV)
    calls = []

    async def fn(a):
        calls.append(a.target.id)
        return a.target.id

    assert asyncio.run(r.run("t", fn, est_tokens=500)) == "gemini:g1"
    assert calls == ["gemini:g1"]
    assert asyncio.run(r.run("t", fn, est_tokens=50)) == "groq:m1"


def test_413_skips_target_learns_limit_and_keeps_keys_ready():
    r = router()
    calls = []

    async def fn(a):
        calls.append(a.target.id)
        if a.target.model == "m1":
            raise FakeErr("Request too large on tokens per minute (TPM): Limit 6000, Requested 9000", 413)
        return a.target.id

    assert asyncio.run(r.run("t", fn, est_tokens=9000)) == "groq:m2"
    assert calls.count("groq:m1") == 1                       # second key not wasted
    assert all(s.is_ready("m1") for s in r.pools["groq"].slots)
    assert r.learned_limits["groq:m1"] == 6000
    calls.clear()
    assert asyncio.run(r.run("t", fn, est_tokens=9000)) == "groq:m2"
    assert "groq:m1" not in calls                            # skipped up front next time


def test_shared_quota_cools_every_key_after_one_429():
    r = LLMRouter(PoolConfig.from_dict(CFG), env={**ENV, "GROQ_SHARED_QUOTA": "true"})
    calls = []

    async def fn(a):
        calls.append(a.label())
        if a.target.provider == "groq":
            raise FakeErr("rate limit", 429, {"retry-after": "30"})
        return a.target.id

    assert asyncio.run(r.run("t", fn)) == "gemini:g1"
    assert len(calls) == 3                                   # one call per groq model, not one per key
    assert all(not s.is_ready("m1") and not s.is_ready("m2") for s in r.pools["groq"].slots)


def test_daily_limit_waits_for_provider_reset():
    from datetime import datetime

    from app.llm.llm_pool.router import seconds_until_reset

    assert seconds_until_reset("UTC", datetime(2026, 11, 24, 23, 0, tzinfo=UTC)) == 3600
    # 08:00 UTC is midnight Pacific (PST): a full day to go
    assert seconds_until_reset("America/Los_Angeles", datetime(2026, 11, 24, 8, 0, tzinfo=UTC)) == 86400

    r = router()
    gemini = r.config.providers["gemini"]          # resets at midnight Pacific by default
    groq = r.config.providers["groq"]              # rolling window: trust the provider's hint
    assert r.daily_cooldown(gemini, 30.0) >= 60
    assert r.daily_cooldown(groq, 179.0) == 180
    assert r.daily_cooldown(groq, None) == 3600


def test_fallback_tier_used_before_waiting_on_cooling_keys():
    cfg = {"max_wait_seconds": 30, "tiers": {"a": ["groq:m1"], "b": ["gemini:g1"]}, "fallbacks": {"a": ["b"]}}
    r = LLMRouter(PoolConfig.from_dict(cfg), env=ENV)
    for s in r.pools["groq"].slots:
        s.model_cooldowns["m1"] = time.time() + 25         # short enough that the old router would sleep 25s

    async def fn(a):
        return a.target.id

    t0 = time.time()
    assert asyncio.run(r.run("a", fn)) == "gemini:g1"
    assert time.time() - t0 < 1


def test_everything_oversized_raises_with_reason():
    cfg = {**CFG, "providers": {"groq": {"max_request_tokens": 10}, "gemini": {"max_request_tokens": 10}}}
    r = LLMRouter(PoolConfig.from_dict(cfg), env=ENV)

    async def fn(a):
        return "never"

    with pytest.raises(AllProvidersFailed, match="request_too_large"):
        asyncio.run(r.run("t", fn, est_tokens=1000))


def test_unknown_fallback_tier_rejected():
    with pytest.raises(ValueError):
        PoolConfig.from_dict({"tiers": {"a": ["groq:m1"]}, "fallbacks": {"a": ["nope"]}})


def test_repo_models_yaml_loads():
    from pathlib import Path

    cfg = PoolConfig.from_yaml(Path(__file__).resolve().parents[1] / "app" / "llm" / "models.yaml")
    assert cfg.providers["groq"].max_request_tokens == 8000
    assert len(cfg.chain("deep")) > len(cfg.tiers["deep"])
    assert cfg.chain("judge") == cfg.tiers["judge"]
