"""Run one chat turn: start the graph in a task, forward its events as they happen."""

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


async def init_graph() -> None:
    """Compile once with a persistent checkpointer (conversation memory per thread)."""
    global _graph, _stack
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = get_settings().checkpoint_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _stack = AsyncExitStack()
    saver = await _stack.enter_async_context(AsyncSqliteSaver.from_conn_string(path))
    _graph = build_graph(checkpointer=saver)


async def close_graph() -> None:
    if _stack:
        await _stack.aclose()


def get_graph():
    global _graph
    if _graph is None:          # tests / scripts without the app lifespan
        _graph = build_graph()
    return _graph


async def run_turn(question: str, thread_id: str | None = None, mode: str = "auto", timezone: str = "UTC",
                   locale: str = "en-US") -> AsyncIterator[dict[str, Any]]:
    """Yields ``{"event", "data"}`` dicts; the last one is ``done`` with the full result."""
    run_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    ctx = RunContext(question=question, timezone=timezone or "UTC", locale=locale or "en-US", mode=mode, queue=queue)
    config = {
        "configurable": {"thread_id": thread_id or run_id},
        "run_name": "search-agent-turn",
        "run_id": uuid.UUID(run_id),
        "metadata": {"thread_id": thread_id, "app_run_id": run_id, "mode": mode},
        "tags": ["react-search-agent", f"mode:{mode}"],
    }
    result: dict[str, Any] = {}
    error: list[str] = []

    async def work():
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
        "usage": {**ctx.usage, "sources": len(ctx.registry), "seconds": round(time.time() - ctx.started, 1)},
    }}
