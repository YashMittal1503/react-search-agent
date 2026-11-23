"""Offline tests for llm_pool (no network). Run: pytest tests/test_llm_pool.py"""

import asyncio
import time

import pytest

from app.llm.llm_pool import ErrorKind, LLMRouter, PoolConfig, classify_error, load_keys, parse_duration, retry_after_seconds
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
