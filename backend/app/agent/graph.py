"""Top-level LangGraph:

    route ──► quick_research  (create_agent ReAct, few steps)        ─┐
          ├─► deep_research   (create_deep_agent: plan + subagents)  ─┼─► synthesize (streamed, citation guard) ─► follow_ups
          └─► (chitchat: no research) ───────────────────────────────┘

Conversation memory is the graph state (``messages``) persisted by a LangGraph checkpointer per thread.
Live UI events (scene, plan, steps, sources, tokens, widgets) go through the RunContext queue.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ContextEditingMiddleware, ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.context_editing import ClearToolUsesEdit
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from ..llm import chat_model
from ..settings import get_settings
from ..tools.agent_tools import QUICK_TOOLS, RESEARCH_TOOLS
from . import prompts
from .citations import CitationStreamer
from .context import RunContext, current_run
from .router import Route, route_question, scene_for

logger = logging.getLogger(__name__)


class State(TypedDict, total=False):
    """The graph state, checkpointed per thread.

    Only ``messages`` accumulates across turns (``add_messages`` appends); the other keys are overwritten each
    turn and describe the current turn only.
    """

    messages: Annotated[list[BaseMessage], add_messages]   # the whole conversation: HumanMessage / AIMessage
    question: str                                          # this turn's user message
    route: dict                                            # router output + scene for this turn
    notes: str                                             # the research agent's final notes for the writer
    answer: str                                            # the final, citation-checked answer


def _today(run: RunContext) -> str:
    """Current date/time in the user's timezone, e.g. 'Tuesday, 24 November 2026, 18:05' (put into prompts)."""
    return run.now.strftime("%A, %d %B %Y, %H:%M")


def _history(messages: list[BaseMessage], limit: int = 6, chars: int = 600) -> str:
    """Render the last ``limit`` messages as 'User: ... / Assistant: ...' lines, each cut to ``chars`` characters.

    Keeps prompts small (free tiers have tight token-per-minute limits) while still letting the router and the
    agents resolve follow-ups such as "and tomorrow?".
    """
    lines = []
    for m in messages[-limit:]:
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        lines.append(f"{role}: {str(m.content)[:chars]}")
    return "\n".join(lines)


def _text(msg: BaseMessage) -> str:
    """A message's text, whether its content is a plain string or a list of content blocks (Gemini returns lists)."""
    c = msg.content
    if isinstance(c, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return str(c or "")


# ── nodes ───────────────────────────────────────────────────────────────────
async def route_node(state: State, config: RunnableConfig) -> dict:
    """Classify the question (intent, quick/deep, location, freshness) and pick the background scene.

    Emits ``route`` and ``scene`` events right away so the UI can switch the scene before research starts.
    """
    run = current_run()
    prior = state.get("messages", [])[:-1]          # everything before this turn's question
    run.step("think", "Understanding the question")
    route: Route = await route_question(state["question"], _history(prior), _today(run), run.timezone, config)
    # The UI's Quick/Deep toggle overrides the router's choice (but chitchat never triggers research).
    if run.mode in ("quick", "deep") and route.intent != "chitchat":
        route.mode = run.mode
    scene = scene_for(route)
    run.route = {**route.model_dump(), **scene}
    run.emit("route", {"intent": route.intent, "mode": route.mode, "query": route.search_query})
    run.emit("scene", {**scene, "final": route.intent != "weather"})   # weather refines once data arrives
    return {"route": run.route}


def _pick(state: State) -> str:
    """Conditional edge after routing: chitchat skips research; otherwise quick or deep research."""
    r = state.get("route", {})
    if r.get("intent") == "chitchat":
        return "synthesize"
    return "deep_research" if r.get("mode") == "deep" else "quick_research"


def _research_input(state: State) -> list:
    """Build the single message a research agent starts from.

    It contains the question plus the router's hints (a standalone rewrite of the query, the location, how fresh
    sources should be) and a short transcript of earlier turns, so follow-ups are researched in context.
    """
    r = state.get("route", {})
    hints = []
    if r.get("search_query") and r["search_query"] != state["question"]:
        hints.append(f"Standalone query: {r['search_query']}")
    if r.get("location"):
        hints.append(f"Location: {r['location']}")
    if r.get("recency_days"):
        hints.append(f"Freshness: prefer sources from the last {r['recency_days']} day(s).")
    history = _history(state.get("messages", [])[:-1], limit=4, chars=400)
    content = state["question"] + ("\n\n" + "\n".join(hints) if hints else "")
    if history:
        content = f"Conversation so far:\n{history}\n\nCurrent question: {content}"
    return [HumanMessage(content)]


def _trim_context(trigger_tokens: int) -> ContextEditingMiddleware:
    """Free tiers have tiny TPM budgets (Groq: 8K/min). Old tool outputs are replaced by a placeholder once the
    context passes ``trigger_tokens``; nothing is lost, because every page excerpt stays in the SourceRegistry
    and the writer reads it from there."""
    return ContextEditingMiddleware(edits=[ClearToolUsesEdit(
        trigger=trigger_tokens, keep=2, exclude_tools=("write_todos",),
        placeholder="[older tool output removed to save tokens; its sources remain citable by id]",
    )])


async def quick_research(state: State, config: RunnableConfig) -> dict:
    """Quick path: a plain ReAct agent (LangChain ``create_agent``) with a small model-call budget.

    Good for facts, weather and news: 1-3 searches or page reads. Its tools register every URL they see in the
    SourceRegistry; the agent's final message becomes ``notes`` for the writer.
    """
    run = current_run()
    s = get_settings()
    agent = create_agent(
        model=chat_model("agent", temperature=0.1),
        tools=QUICK_TOOLS,
        system_prompt=prompts.QUICK.format(today=_today(run), tz=run.timezone, locale=run.locale, max_calls=s.quick_max_model_calls),
        # Stop (rather than error) after N model calls; trim old tool outputs to stay under Groq's 8K TPM.
        middleware=[ModelCallLimitMiddleware(run_limit=s.quick_max_model_calls, exit_behavior="end"), _trim_context(4500)],
        name="quick_research",
    )
    notes = await _run_agent(agent, _research_input(state), config, timeout=75)
    return {"notes": notes}


async def deep_research(state: State, config: RunnableConfig) -> dict:
    """Deep path: a ``deepagents`` agent that plans with todos and delegates sub-questions to a subagent.

    The planner writes a todo list (streamed to the UI as the plan), may keep notes in deepagents' virtual
    filesystem, and hands self-contained sub-questions to ``web-researcher``. Budgets (model calls, searches,
    wall-clock timeout) keep one run within free-tier quotas.
    """
    from deepagents import create_deep_agent  # imported lazily: heavy import, only needed for deep runs

    run = current_run()
    s = get_settings()
    today = _today(run)
    researcher = {
        "name": "web-researcher",
        "description": "Researches ONE self-contained sub-question on the web (e.g. 'best neighbourhoods to stay in Kyoto') "
                       "and returns cited bullet findings. Give it a precise task description.",
        "system_prompt": prompts.RESEARCHER.format(today=today),
        "tools": RESEARCH_TOOLS,
        "model": chat_model("agent", temperature=0.1),
        "middleware": [ModelCallLimitMiddleware(run_limit=6, exit_behavior="end"), _trim_context(3500)],
    }
    agent = create_deep_agent(
        model=chat_model("deep", temperature=0.1),
        tools=RESEARCH_TOOLS,
        system_prompt=prompts.DEEP.format(today=today, tz=run.timezone, locale=run.locale, max_calls=s.deep_max_model_calls),
        subagents=[researcher],
        middleware=[
            ModelCallLimitMiddleware(run_limit=s.deep_max_model_calls, exit_behavior="end"),
            ToolCallLimitMiddleware(tool_name="web_search", run_limit=12),   # free search engines throttle bursts
            _trim_context(9000),
        ],
        name="deep_research",
    )
    notes = await _run_agent(agent, _research_input(state), config, timeout=s.deep_timeout_seconds, track_todos=True)
    return {"notes": notes}


async def _run_agent(agent, messages: list, config: RunnableConfig, timeout: float, track_todos: bool = False) -> str:
    """Run a research agent to completion (or until ``timeout``) and return its notes for the writer.

    The agent's state is streamed (``stream_mode="values"``) so todo-list changes reach the UI as ``plan`` events
    while it works. On timeout or failure nothing is lost: every source the tools found is already in the
    SourceRegistry, and the writer answers from whatever was gathered.

    Returns:
        The last plain AI message (no tool calls), plus up to 4 notes files from deepagents' virtual filesystem.
    """
    run = current_run()
    last: dict[str, Any] = {}       # most recent full agent state
    todos_seen: list = []           # last plan sent to the UI (only re-emit when it changes)

    async def consume():
        """Drain the agent's state stream, forwarding plan changes."""
        nonlocal last, todos_seen
        async for state in agent.astream({"messages": messages}, config={**config, "recursion_limit": 60}, stream_mode="values"):
            last = state
            todos = state.get("todos") if track_todos else None
            if todos and todos != todos_seen:
                todos_seen = list(todos)
                run.emit("plan", {"todos": [{"content": t.get("content"), "status": t.get("status")} for t in todos]})

    try:
        await asyncio.wait_for(consume(), timeout=timeout)
    except TimeoutError:
        run.emit("notice", {"message": "Research hit the time budget; writing the answer from what was found."})
    except Exception as err:  # noqa: BLE001
        logger.exception("research agent failed")
        run.emit("notice", {"message": f"Research step failed ({type(err).__name__}); answering from sources found so far."})

    # The agent's conclusion is its last text-only message (messages with tool calls are intermediate steps).
    notes = ""
    msgs = last.get("messages") or []
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and _text(m).strip() and not m.tool_calls:
            notes = _text(m)
            break
    files = last.get("files") or {}
    for path, f in list(files.items())[:4]:   # deepagents notes written to its virtual filesystem
        content = f.get("content") if isinstance(f, dict) else f
        if isinstance(content, list):
            content = "\n".join(map(str, content))
        if content:
            notes += f"\n\n--- notes file {path} ---\n{str(content)[:3000]}"
    run.notes.append(notes)
    return notes


def _sources_block(run: RunContext) -> str:
    """Format the evidence for the writer: one ``[S#] title | domain | date`` block per source.

    At most ``max_sources_in_context`` sources, preferring pages that were actually read over bare search
    snippets, within a total budget of ~14K tokens. Blocks are listed in id order so ``[S#]`` ids read naturally.
    """
    s = get_settings()
    srcs = run.registry.all()
    # fetched pages first (they have real content), then search hits with snippets
    ranked = sorted(srcs, key=lambda x: (not x.fetched, x.id))[: s.max_sources_in_context]
    blocks = []
    budget = 14000 * 4          # characters (~4 chars per token)
    for src in sorted(ranked, key=lambda x: x.id):
        body = src.content or src.snippet
        date = f" | published {src.published[:10]}" if src.published else ""
        block = f"[S{src.id}] {src.title} | {src.domain}{date}\n{body}"
        if budget - len(block) < 0:
            block = block[: max(400, budget)]   # cut the last block to fit, but keep at least its header + a snippet
        budget -= len(block)
        blocks.append(block)
        if budget <= 0:
            break
    return "\n\n".join(blocks) or "(no sources)"


async def synthesize(state: State, config: RunnableConfig) -> dict:
    """Write the final answer, streaming tokens to the UI through the citation guard.

    The writer (long-context tier) sees the sources block and the research notes and cites sources as ``[S#]``.
    :class:`CitationStreamer` rewrites those to ``[1]``, ``[2]``... as tokens stream, drops ids that don't exist
    and strips raw URLs, so every citation chip in the UI links to a page a tool really returned.
    Chitchat skips sources entirely and just converses.
    """
    run = current_run()
    route = state.get("route", {})
    today = _today(run)
    history = state.get("messages", [])[:-1][-6:]   # up to 3 earlier exchanges
    if route.get("intent") == "chitchat":
        system = prompts.CHITCHAT.format(today=today)
        msgs = [("system", system), *[(("human" if isinstance(m, HumanMessage) else "ai"), _text(m)) for m in history], ("human", state["question"])]
    else:
        extra = ""
        if not len(run.registry):
            extra = "\nNo sources were found. Say so briefly and answer only what is common knowledge, marked as unverified.\n"
        system = prompts.SYNTHESIZE.format(today=today, tz=run.timezone, locale=run.locale, extra=extra,
                                           sources=_sources_block(run), notes=state.get("notes") or "(none)")
        convo = "\n".join(f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {_text(m)[:500]}" for m in history)
        human = (f"Earlier conversation:\n{convo}\n\n" if convo else "") + f"Question: {state['question']}"
        msgs = [("system", system), ("human", human)]

    sid = run.step("write", "Writing the answer")
    streamer = CitationStreamer(run.registry)
    parts: list[str] = []
    llm = chat_model("long_context", temperature=0.3)
    try:
        async for chunk in llm.astream(msgs, config=config):
            out = streamer.feed(chunk.text if hasattr(chunk, "text") else str(chunk.content))
            if out:
                parts.append(out)
                run.emit("token", {"text": out})
    except Exception as err:  # noqa: BLE001 - every tier failed: tell the user instead of erroring the stream
        logger.exception("synthesis failed")
        msg = "\n\n_I couldn't finish writing the answer: every model tier is rate-limited right now. Please try again in a minute._"
        parts.append(msg)
        run.emit("token", {"text": msg})
        run.emit("notice", {"message": f"Writer failed: {str(err)[:160]}"})
    tail = streamer.flush()      # text held back because it might have been the start of a citation marker
    if tail:
        parts.append(tail)
        run.emit("token", {"text": tail})
    answer = "".join(parts).strip()
    run.step_update(sid, "done")
    cited = streamer.cited_sources()
    run.emit("citations", {"sources": cited, "invalid_removed": streamer.invalid})
    run.route["cited"] = cited
    run.route["invalid_citations"] = streamer.invalid
    return {"answer": answer, "messages": [AIMessage(answer)]}


class FollowUps(BaseModel):
    """Structured output of the follow-up step."""

    follow_ups: list[str] = Field(description="3 short follow-up questions")
    title: str | None = Field(default=None, description="3-6 word chat title, only if asked")


async def follow_ups(state: State, config: RunnableConfig) -> dict:
    """Suggest 3 follow-up questions (UI chips) and, on a thread's first turn, a short chat title.

    Best-effort: uses the cheap ``fast`` tier with a 20 s cap and silently skips on any failure.
    """
    run = current_run()
    first = len([m for m in state.get("messages", []) if isinstance(m, HumanMessage)]) <= 1   # first turn of the thread
    try:
        llm = chat_model("fast", temperature=0.4).with_structured_output(FollowUps)
        res = await asyncio.wait_for(llm.ainvoke([("human", prompts.FOLLOWUPS.format(
            question=state["question"], answer=(state.get("answer") or "")[:1500],
            title_instruction="Also give a 3-6 word title for this chat." if first else "Set title to null.",
        ))], config=config), timeout=20)
        if not isinstance(res, FollowUps):
            res = FollowUps.model_validate(res)
        run.emit("followups", {"items": [q.strip() for q in res.follow_ups[:3] if q.strip()]})
        if first and res.title:
            run.route["title"] = res.title.strip().strip('"')[:60]
            run.emit("title", {"title": run.route["title"]})
    except Exception as err:  # noqa: BLE001
        logger.info("follow-ups skipped: %s", str(err)[:120])
    return {}


def build_graph(checkpointer=None):
    """Assemble and compile the graph drawn in the module docstring.

    Args:
        checkpointer: a LangGraph saver that persists each thread's state (conversation memory). ``None`` means
            no memory between turns.
    """
    g = StateGraph(State)
    g.add_node("route", route_node)
    g.add_node("quick_research", quick_research)
    g.add_node("deep_research", deep_research)
    g.add_node("synthesize", synthesize)
    g.add_node("follow_ups", follow_ups)
    g.add_edge(START, "route")
    g.add_conditional_edges("route", _pick, ["quick_research", "deep_research", "synthesize"])
    g.add_edge("quick_research", "synthesize")
    g.add_edge("deep_research", "synthesize")
    g.add_edge("synthesize", "follow_ups")
    g.add_edge("follow_ups", END)
    return g.compile(checkpointer=checkpointer, name="react-search-agent")
