"""Citation formats seen from real models (LangSmith traces): all must become numbered chips, none dropped."""

from app.agent.citations import CitationStreamer, rewrite_all
from app.agent.context import SourceRegistry


def _registry(n: int = 12) -> SourceRegistry:
    """A registry with sources S1..Sn."""
    reg = SourceRegistry()
    for i in range(1, n + 1):
        reg.add(f"https://example.com/{i}", f"Source {i}")
    return reg


def test_fullwidth_brackets_from_gpt_oss():
    """gpt-oss writes 【S11】 and 【S11†L5-L9】; the guard used to ignore them, leaving zero cited sources."""
    text, cs = rewrite_all("Camp costs ₹2,250【S11】 and yoga starts 7:30【S12†L5-L9】.", _registry())
    assert text == "Camp costs ₹2,250[1] and yoga starts 7:30[2]."
    assert [s["id"] for s in cs.cited_sources()] == [11, 12]


def test_parenthesised_ids_but_not_years():
    text, cs = rewrite_all("Alcohol is banned (S3, S4). Founded (2024).", _registry())
    assert text == "Alcohol is banned [1][2]. Founded (2024)."
    assert len(cs.cited_sources()) == 2


def test_fullwidth_marker_split_across_tokens():
    cs = CitationStreamer(_registry())
    out = "".join(cs.feed(t) for t in ["Price ₹3,500", "【S", "11", "】 total"]) + cs.flush()
    assert out == "Price ₹3,500[1] total"
