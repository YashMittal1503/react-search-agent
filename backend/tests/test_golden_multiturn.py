"""Offline tests for the golden-set schema rules and the multi-turn eval runner (no LLM, no network).

The agent itself is replaced by a fake ``run_turn`` that remembers what each thread was told, so we can check that
every turn of an item runs in the same thread and that turn results roll up correctly into one item result.
"""

from __future__ import annotations

import pytest

from evals import runner
from evals.runner import DATA, run_item, summarize
from evals.schema import GoldItem, load


def test_every_item_states_route_and_difficulty():
    """The dataset contract: each item/turn has an expected route, robustness items say what they test."""
    items = load(DATA, "http://127.0.0.1:8765")
    assert 60 <= len(items) <= 75
    for i in items:
        assert i.difficulty in {"easy", "medium", "hard"}
        assert all(t.expected_mode in {"quick", "deep"} for t in i.all_turns()), i.id
        if i.category == "robustness":
            assert i.focus and i.label.startswith("robustness (")
    assert sum(i.category == "multi_turn" for i in items) >= 6
    assert not any(i.category == "non_english" for i in items)


def test_schema_rejects_bad_shapes():
    """Exactly one of query/turns; at least two turns; robustness needs a focus; difficulty is mandatory."""
    base = {"id": "x", "category": "static_fact", "difficulty": "easy", "expected_mode": "quick"}
    with pytest.raises(ValueError):
        GoldItem.model_validate(base)                                            # neither query nor turns
    with pytest.raises(ValueError):
        GoldItem.model_validate({**base, "query": "q", "turns": [{"query": "a", "expected_mode": "quick"}] * 2})
    with pytest.raises(ValueError):
        GoldItem.model_validate({**base, "category": "multi_turn", "turns": [{"query": "a", "expected_mode": "quick"}]})
    with pytest.raises(ValueError):
        GoldItem.model_validate({**base, "category": "robustness", "query": "q"})  # missing focus
    with pytest.raises(ValueError):
        GoldItem.model_validate({"id": "y", "category": "static_fact", "query": "q", "expected_mode": "quick"})
    assert GoldItem.model_validate({**base, "query": "q"}).all_turns()[0].query == "q"


@pytest.fixture
def fake_agent(monkeypatch):
    """Replace the agent with a stub that answers from a script and records (thread_id, question) pairs."""
    calls: list[tuple[str, str]] = []
    answers = {"How tall is it?": "Which building do you mean?", "The Burj Khalifa": "It is 828 metres tall [1]."}

    async def fake_run_turn(question, thread_id, mode, tz, locale, capture=None):
        calls.append((thread_id, question))
        cited = [{"n": 1, "id": "S1", "url": "https://x.org/a", "domain": "x.org"}] if "[1]" in answers[question] else []
        yield {"event": "done", "data": {
            "run_id": f"run-{len(calls)}", "answer": answers[question], "sources": cited,
            "all_sources": [{"url": "https://x.org/a"}],
            "usage": {"searches": len(cited), "tokens": {
                "calls": 1, "input_tokens": 100, "output_tokens": 20, "cached_tokens": 0, "reasoning_tokens": 0,
                "total_tokens": 120, "estimated_calls": 0, "by_step": {"quick_research": 120},
                "by_model": [{"provider": "groq", "model": "m1", "calls": 1, "input_tokens": 100, "output_tokens": 20,
                              "cached_tokens": 0, "reasoning_tokens": 0, "total_tokens": 120, "estimated_calls": 0}]}},
            "route": {"intent": "general", "mode": "quick"}, "invalid_citations": [],
        }}

    monkeypatch.setattr(runner, "run_turn", fake_run_turn)
    return calls


async def test_multi_turn_items_share_one_thread_and_roll_up(fake_agent):
    item = next(i for i in load(DATA) if i.id == "mt-clarify-then-answer")
    r = await run_item(item, judge=False)
    threads = {t for t, _ in fake_agent}
    assert len(fake_agent) == 2 and len(threads) == 1            # both turns, same conversation
    assert r["passed"] and r["turns_count"] == 2 and len(r["turns"]) == 2
    assert r["metrics"]["route_mode"] == ["quick", "quick"] and r["turn_routing"] == [True, True]
    s = summarize([r])
    assert s["turns"] == 2 and s["routing_accuracy"] == 1.0
    # tokens: per turn, rolled up per item (2 turns x 120) and per suite, judge kept separate (no judge here)
    assert r["turns"][1]["tokens"]["total_tokens"] == 120
    assert r["tokens"]["total_tokens"] == 240 and r["tokens"]["by_model"][0]["calls"] == 2
    assert r["metrics"]["total_tokens"] == 240 and r["judge_tokens"]["calls"] == 0
    assert s["tokens"]["total_tokens"] == 240 and s["avg_tokens"] == 240


async def test_failures_name_the_turn(fake_agent, monkeypatch):
    """When turn 2 fails, the item fails and the reason is prefixed with 't2:'."""
    item = next(i for i in load(DATA) if i.id == "mt-clarify-then-answer")
    item.turns[1].assertions[0].value = 999          # turn 2 now expects a height the stub never says
    r = await run_item(item, judge=False)
    assert not r["passed"]
    assert any(c["why"].startswith("t2:") for c in r["checks"] if not c["ok"])
