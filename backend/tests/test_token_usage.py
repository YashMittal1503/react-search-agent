"""Offline tests for token accounting: the callback tracker, storage per run, and eval roll-ups (no network)."""

from __future__ import annotations

import uuid

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.llm.usage import TokenTracker, merge_summaries


def _end(tracker: TokenTracker, target: str, usage: dict | None, text: str = "hi", metadata: dict | None = None) -> None:
    """Drive one call through the tracker's start/end hooks, as LangChain would."""
    rid = uuid.uuid4()
    tracker.on_chat_model_start({}, [[HumanMessage("x" * 400)]], run_id=rid, metadata=metadata or {})
    msg = AIMessage(text, response_metadata={"llm_pool_target": target}, usage_metadata=usage)
    tracker.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=rid)


def test_tracker_uses_provider_usage_and_groups_by_model_and_step():
    t = TokenTracker()
    usage = {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500,
             "input_token_details": {"cache_read": 1000}, "output_token_details": {"reasoning": 120}}
    _end(t, "groq:openai/gpt-oss-120b", usage, metadata={"checkpoint_ns": "quick_research:abc|model:def"})
    _end(t, "groq:openai/gpt-oss-120b", usage, metadata={"langgraph_node": "route"})
    _end(t, "gemini:gemini-3.8-flash", None, text="y" * 80, metadata={"langgraph_node": "synthesize"})
    s = t.summary()
    assert s["calls"] == 3 and s["estimated_calls"] == 1
    top = s["by_model"][0]
    assert (top["provider"], top["model"], top["calls"]) == ("groq", "openai/gpt-oss-120b", 2)
    assert top["cached_tokens"] == 2000 and top["reasoning_tokens"] == 240
    gem = s["by_model"][1]
    assert gem["input_tokens"] == 100 and gem["output_tokens"] == 20        # estimated at 4 chars/token
    assert s["by_step"] == {"quick_research": 1500, "route": 1500, "synthesize": 120}


async def test_tracker_sees_calls_through_langchain_callbacks():
    """Attached via config, the tracker is called for a real LangChain model call (no usage -> estimated)."""
    t = TokenTracker(default_step="judge")
    llm = GenericFakeChatModel(messages=iter([AIMessage("ok")]))
    await llm.ainvoke("hello there", config={"callbacks": [t]})
    s = t.summary()
    assert s["calls"] == 1 and s["estimated_calls"] == 1 and s["by_step"] == {"judge": s["total_tokens"]}


def test_merge_summaries_adds_up_runs():
    a, b = TokenTracker(), TokenTracker()
    _end(a, "groq:m1", {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    _end(b, "groq:m1", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    _end(b, "nvidia:m2", {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
    m = merge_summaries([a.summary(), None, b.summary()])
    assert m["calls"] == 3 and m["total_tokens"] == 167
    assert [r["model"] for r in m["by_model"]] == ["m2", "m1"] and m["by_model"][1]["calls"] == 2


async def test_usage_is_stored_per_run_and_summarised(tmp_path, monkeypatch):
    from app.settings import get_settings
    from app.store import db

    monkeypatch.setattr(get_settings(), "database_url", f"sqlite+aiosqlite:///{(tmp_path / 't.db').as_posix()}")
    await db.init_db()
    t = TokenTracker()
    _end(t, "groq:m1", {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    _end(t, "gemini:m2", {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10})
    assert await db.add_token_usage("run-1", "thread-1", t.summary(), mode="quick") == 2
    assert await db.add_token_usage("run-2", None, {"by_model": []}) == 0          # no calls, no rows
    rows = await db.usage_for_run("run-1")
    assert {(r["provider"], r["total_tokens"]) for r in rows} == {("groq", 15), ("gemini", 10)}
    s = await db.usage_summary(days=1, source="chat")
    assert s["runs"] == 1 and s["totals"]["total_tokens"] == 25 and s["by_model"][0]["provider"] == "groq"
