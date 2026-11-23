"""Fetch waterfall against the local fixture site (no internet), SSRF guard, eval scoring and dataset."""

import pytest

from app.settings import get_settings
from app.tools.fetch import waterfall
from evals import scoring
from evals.fixtures_site import serve_in_background
from evals.runner import DATA, summarize
from evals.schema import Assertion, load


@pytest.fixture(scope="module")
def site():
    return serve_in_background()


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Allow 127.0.0.1, disable cache and the internet-facing tiers (Jina, Wayback)."""
    s = get_settings()
    monkeypatch.setattr(s, "allow_private_fetch", True)

    async def fail(url, client):
        return waterfall.FetchResult(url, False, tier="offline", status="error", error="offline test")

    monkeypatch.setattr(waterfall, "_jina", fail)
    monkeypatch.setattr(waterfall, "_wayback", fail)
    monkeypatch.setattr(waterfall.cache, "get", lambda k: None)
    monkeypatch.setattr(waterfall.cache, "set", lambda *a, **k: None)


async def test_article_is_extracted(site, offline):
    r = await waterfall.fetch(site + "/article")
    assert r.ok and r.status == "ok" and r.tier == "http"
    assert "2031" in r.text and "412 metres" in r.text
    assert "Project Lumen" in r.title


async def test_pdf_is_parsed(site, offline):
    r = await waterfall.fetch(site + "/report.pdf")
    assert r.ok and "ZEPHYR-42" in r.text and r.tier == "http:pdf"


async def test_blocked_and_js_only_fail_cleanly(site, offline):
    blocked = await waterfall.fetch(site + "/blocked")
    assert not blocked.ok and blocked.status == "blocked"
    js = await waterfall.fetch(site + "/js-only")
    assert not (js.ok and js.status == "ok")
    assert any("http" in t for t in js.tried)


async def test_ssrf_guard_blocks_private_addresses():
    assert get_settings().allow_private_fetch is False
    r = await waterfall.fetch("http://127.0.0.1:8765/article")
    assert not r.ok and "private" in r.error
    assert waterfall.is_private_url("http://localhost/x")
    assert waterfall.is_private_url("http://10.0.0.5/")
    assert not waterfall.is_private_url("https://93.184.215.14/")


def test_golden_dataset_is_valid():
    items = load(DATA, "http://127.0.0.1:8765")
    assert len(items) >= 60
    assert all("{FIXTURE}" not in i.query for i in items)
    assert any(i.smoke for i in items) and any(i.split == "holdout" for i in items)


RUN = {
    "answer": "Canberra is the capital [1]. It was chosen in 1908 [2].",
    "sources": [{"n": 1, "url": "https://a.gov.au/x", "domain": "a.gov.au", "published": "2026-11-20"},
                {"n": 2, "url": "https://b.org/y", "domain": "b.org", "published": None}],
    "all_sources": [{"url": "https://a.gov.au/x"}, {"url": "https://b.org/y"}, {"url": "https://c.com"}],
    "steps": [{"kind": "search"}, {"kind": "fetch"}],
    "usage": {"seconds": 4.2, "searches": 1, "fetches": 1},
    "route": {"intent": "general", "mode": "quick"},
}


def test_assertions():
    ok = lambda **k: scoring.check(Assertion(**k), RUN)[0]  # noqa: E731
    assert ok(type="contains_any", values=["canberra"])
    assert ok(type="numeric", value=1908, tolerance=0)
    assert not ok(type="numeric", value=1901, tolerance=0)
    assert ok(type="must_call_tool", value="fetch_page")
    assert not ok(type="must_call_tool", value="get_weather")
    assert ok(type="must_cite_domain", value="gov.au")
    assert ok(type="min_sources", value=2)
    assert ok(type="freshness_days", value=30)
    assert not ok(type="no_tool_calls")
    assert not ok(type="should_refuse")


def test_refusal_and_clarify_detection():
    refuse = {"answer": "I'm sorry, but I can't help with making explosives."}
    assert scoring.check(Assertion(type="should_refuse"), refuse)[0]
    clarify = {"answer": "Could you tell me which building you mean?", "sources": []}
    assert scoring.check(Assertion(type="should_clarify"), clarify)[0]


def test_global_metrics_catch_unmapped_citations():
    assert scoring.global_metrics(RUN)["citation_validity"] == 1.0
    bad = {**RUN, "answer": RUN["answer"] + " Extra [3]."}
    assert scoring.global_metrics(bad)["citation_validity"] == 0.0


def test_summary_shape():
    r = {"id": "x", "category": "static_fact", "passed": True, "assertion_pass": True, "routing_ok": True,
         "metrics": scoring.global_metrics(RUN), "checks": []}
    s = summarize([r])
    assert s["pass_rate"] == 1.0 and s["by_category"]["static_fact"]["n"] == 1
