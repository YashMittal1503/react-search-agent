"""Offline tests: citation guard, source registry, router heuristics, extraction."""

from app.agent.citations import CitationStreamer, rewrite_all
from app.agent.context import SourceRegistry, canonical_url
from app.agent.router import heuristic_route, scene_for
from app.tools.fetch.extract import chunk, quality, select_relevant


def registry(n=3):
    """A SourceRegistry pre-filled with ``n`` fake sources (ids S1..Sn)."""
    r = SourceRegistry()
    for i in range(n):
        r.add(f"https://example{i}.com/page", f"Title {i}", "snippet")
    return r


def test_registry_dedupes_tracking_params_and_www():
    r = SourceRegistry()
    a, new_a = r.add("https://www.site.com/a/?utm_source=x&id=2", "A")
    b, new_b = r.add("http://site.com/a?id=2", "A again")
    assert new_a and not new_b and a.id == b.id
    assert canonical_url("https://WWW.Site.com/a/") == "https://site.com/a"


def test_citations_renumber_in_order_of_first_use_and_drop_invalid():
    text, cs = rewrite_all("Kyoto has temples [S3]. Trains are fast [S1][S3]. Fake [S99]. Grouped [S1, S2].", registry(3))
    assert text == "Kyoto has temples [1]. Trains are fast [2][1]. Fake . Grouped [2][3]."
    assert [s["n"] for s in cs.cited_sources()] == [1, 2, 3]
    assert cs.cited_sources()[0]["url"] == "https://example2.com/page"
    assert cs.invalid == ["S99"]


def test_citation_streamer_handles_markers_split_across_tokens():
    cs = CitationStreamer(registry(2))
    out = "".join(cs.feed(t) for t in ["Fact one [", "S", "2", "] and two [S1", "]."]) + cs.flush()
    assert out == "Fact one [1] and two [2]."


def test_citation_streamer_strips_raw_urls():
    cs = CitationStreamer(registry(1))
    out = cs.feed("See https://evil.example/x for more [S1].") + cs.flush()
    assert "http" not in out and out.endswith("[1].")


def test_citation_streamer_keeps_normal_brackets():
    cs = CitationStreamer(registry(1))
    out = cs.feed("An array [a, b] and [note] stay.") + cs.flush()
    assert out == "An array [a, b] and [note] stay."


def test_heuristic_router():
    assert heuristic_route("What's the weather in Mumbai today?").intent == "weather"
    assert heuristic_route("Plan a 4-day Kyoto itinerary").mode == "deep"
    assert heuristic_route("hi!").intent == "chitchat"
    r = heuristic_route("latest AI news")
    assert r.intent == "news" and r.recency_days == 1
    assert scene_for(heuristic_route("Will it rain in London?"))["scene"] == "weather"


def test_quality_detects_bot_walls_and_js_shells():
    assert quality("Please enable JavaScript to continue.") == "blocked"
    assert quality("Just a moment... Checking your browser before accessing.") == "blocked"
    assert quality("short") == "thin"
    assert quality("Real article sentence with content. " * 40) == "ok"


def test_select_relevant_keeps_lead_and_relevant_chunks_within_budget():
    paras = ["Intro paragraph about the city of Kyoto and its history. " * 6]
    paras += [f"Unrelated filler paragraph number {i} about nothing much. " * 6 for i in range(20)]
    paras.insert(12, "Fushimi Inari shrine opens 24 hours and entry is free of charge. " * 4)
    text = "\n\n".join(paras)
    out = select_relevant(text, "Fushimi Inari opening hours entry fee", budget_tokens=300)
    assert out.startswith("Intro paragraph")
    assert "Fushimi Inari shrine opens 24 hours" in out
    assert len(out) <= 300 * 4 + 200


def test_chunk_attaches_headings():
    chunks = chunk("# Title\n\nPara one.\n\n## Section\n\nPara two.", target_chars=20)
    assert any(c.startswith("## Section") for c in chunks)
