"""Run one chat turn and stream what the agent does.

The LangGraph graph (``graph.py``) is compiled once per process. ``run_turn`` starts it in a background task and
forwards the events that tools and nodes push onto the run's queue (plan, steps, sources, answer tokens...), so the
API can relay them to the browser over SSE while the graph is still working. The final ``done`` event carries the
complete result (answer, cited sources, widgets, route, usage).

How events get from deep inside a tool to here: ``RunContext`` (``context.py``) is stored in a ContextVar for the
duration of the turn; tools call ``current_run().emit(...)``, which puts the event on ``queue``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any

from langchain_core.messages import HumanMessage

from ..settings import get_settings
from .context import RunContext, reset_run, set_run
from .graph import build_graph

logger = logging.getLogger(__name__)

_graph = None
_stack: AsyncExitStack | None = None


async def init_graph(memory: bool = False) -> None:
    """Compile the graph once, with a checkpointer that stores each thread's conversation.

    Args:
        memory: use an in-process ``InMemorySaver`` instead of the SQLite file. Evals use this so multi-turn
            items get thread memory without touching the app's real checkpoint database.
    """
    global _graph, _stack
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    if memory:
        from langgraph.checkpoint.memory import InMemorySaver

        _graph = build_graph(checkpointer=InMemorySaver())
        return
    path = get_settings().checkpoint_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _stack = AsyncExitStack()
    saver = await _stack.enter_async_context(AsyncSqliteSaver.from_conn_string(path))
    _graph = build_graph(checkpointer=saver)


async def close_graph() -> None:
    """Close the SQLite checkpointer connection (called on app shutdown)."""
    if _stack:
        await _stack.aclose()


def get_graph():
    """The compiled graph; builds one without memory if ``init_graph`` was never called (tests, quick scripts)."""
    global _graph
    if _graph is None:          # tests / scripts without the app lifespan
        _graph = build_graph()
    return _graph


async def run_turn(question: str, thread_id: str | None = None, mode: str = "auto", timezone: str = "UTC",
                   locale: str = "en-US", capture: list | None = None) -> AsyncIterator[dict[str, Any]]:
    """Run one user message through the agent, yielding ``{"event", "data"}`` dicts as things happen.

    Args:
        question: the user's message.
        thread_id: conversation id; earlier turns of the same thread are loaded from the checkpointer.
            ``None`` means a one-off turn with no memory.
        mode: ``auto`` lets the router decide; ``quick`` / ``deep`` force a path (the UI's mode toggle).
        timezone, locale: from the browser, so "today" and number formats are the user's.
        capture: if a list is given, the turn's RunContext is appended to it (evals read the source registry
            to see exactly which excerpts the writer was given).

    Yields:
        ``start`` first, then streamed events (``scene``, ``plan``, ``step``, ``token``, ``widget``, ...), an
        ``error`` if the graph failed without an answer, and finally ``done`` with the full result.
    """
    run_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    ctx = RunContext(question=question, timezone=timezone or "UTC", locale=locale or "en-US", mode=mode, queue=queue)
    if capture is not None:
        capture.append(ctx)
    config = {
        "configurable": {"thread_id": thread_id or run_id},
        "run_name": "search-agent-turn",
        "run_id": uuid.UUID(run_id),
        "metadata": {"thread_id": thread_id, "app_run_id": run_id, "mode": mode},
        "tags": ["react-search-agent", f"mode:{mode}"],
        # LangChain passes callbacks down to every nested run, so the tracker sees the router, both research
        # agents (and deepagents' subagents), the writer and follow-ups.
        "callbacks": [ctx.tokens],
    }
    result: dict[str, Any] = {}
    error: list[str] = []

    async def work():
        """Run the graph with this turn's RunContext active; always end the stream with a ``None`` sentinel."""
        token = set_run(ctx)
        try:
            import logfire

            with logfire.span("chat turn", run_id=run_id, thread_id=thread_id, mode=mode, question=question[:200]):
                out = await get_graph().ainvoke({"messages": [HumanMessage(question)], "question": question}, config=config)
            result.update(out or {})
        except Exception as err:  # noqa: BLE001
            logger.exception("turn failed")
            error.append(f"{type(err).__name__}: {str(err)[:300]}")
        finally:
            reset_run(token)
            queue.put_nowait(None)

    yield {"event": "start", "data": {"run_id": run_id, "thread_id": thread_id}}
    task = asyncio.create_task(work())
    # Relay events until the sentinel. If the consumer stops early (client disconnected), cancel the graph.
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()

    if error and not result.get("answer"):
        yield {"event": "error", "data": {"message": "The agent failed to answer. " + error[0]}}
    route = ctx.route
    yield {"event": "done", "data": {
        "run_id": run_id,
        "answer": result.get("answer", ""),
        "sources": route.get("cited", []),
        "all_sources": [s.public() for s in ctx.registry.all()],
        "widgets": ctx.widgets,
        "route": {k: route.get(k) for k in ("intent", "mode", "scene", "params", "location", "search_query")},
        "title": route.get("title"),
        "invalid_citations": route.get("invalid_citations", []),
        "usage": {**ctx.usage, "llm_calls": len(ctx.tokens.calls), "sources": len(ctx.registry),
                  "seconds": round(time.time() - ctx.started, 1),
                  "tokens": ctx.tokens.summary()},          # totals + by_model + by_step
    }}
