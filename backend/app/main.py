"""FastAPI app: SSE chat + thread CRUD for anonymous clients."""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .agent.runner import close_graph, init_graph, run_turn
from .api import limits
from .api.suggestions import SUGGESTIONS
from .llm import get_router
from .observability import flush_traces, setup_observability
from .settings import get_settings
from .store import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    await init_graph()
    yield
    await close_graph()
    flush_traces()


app = FastAPI(title="react-search-agent", version="0.1.0", lifespan=lifespan)
setup_observability(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().frontend_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

_CLIENT_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def _owner(client_id: str | None) -> str:
    if not client_id or not _CLIENT_RE.match(client_id):
        raise HTTPException(400, "Missing or invalid X-Client-Id header")
    return client_id


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None
    mode: Literal["auto", "quick", "deep"] = "auto"
    timezone: str = "UTC"
    locale: str = "en-US"


class ThreadPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/api/status")
async def status():
    s = get_settings()
    return {
        "llm_keys": {k: v for k, v in get_router().key_counts().items() if v},
        "search": {"tavily": bool(s.tavily_api_key), "exa": bool(s.exa_api_key), "searxng": bool(s.searxng_url), "duckduckgo": True},
        "browser_fetch": s.enable_browser_fetch,
        "limits": {"chat_per_day": s.rate_limit_per_day, "deep_per_day": s.deep_rate_limit_per_day},
    }


@app.get("/api/suggestions")
async def suggestions():
    return SUGGESTIONS


@app.get("/api/threads")
async def threads(x_client_id: str | None = Header(default=None)):
    return await db.list_threads(_owner(x_client_id))


@app.post("/api/threads")
async def new_thread(x_client_id: str | None = Header(default=None)):
    return await db.create_thread(_owner(x_client_id))


@app.patch("/api/threads/{thread_id}")
async def patch_thread(thread_id: str, body: ThreadPatch, x_client_id: str | None = Header(default=None)):
    t = await db.update_thread(_owner(x_client_id), thread_id, title=body.title, pinned=body.pinned)
    if not t:
        raise HTTPException(404, "thread not found")
    return t


@app.delete("/api/threads/{thread_id}")
async def remove_thread(thread_id: str, x_client_id: str | None = Header(default=None)):
    if not await db.delete_thread(_owner(x_client_id), thread_id):
        raise HTTPException(404, "thread not found")
    return {"ok": True}


@app.get("/api/threads/{thread_id}/messages")
async def messages(thread_id: str, x_client_id: str | None = Header(default=None)):
    if not await db.get_thread(_owner(x_client_id), thread_id):
        raise HTTPException(404, "thread not found")
    return await db.list_messages(thread_id)


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request, x_client_id: str | None = Header(default=None)):
    owner = _owner(x_client_id)
    s = get_settings()
    limits.check(request, "chat", s.rate_limit_per_day)
    if body.mode == "deep":
        limits.check(request, "deep research", s.deep_rate_limit_per_day)

    thread = await db.get_thread(owner, body.thread_id) if body.thread_id else None
    if thread is None:
        thread_id = (await db.create_thread(owner))["id"]
    else:
        thread_id = thread.id
    await db.add_message(thread_id, "user", body.message)

    async def events():
        steps: dict[int, dict] = {}
        plan: list = []
        followups: list = []
        yield {"event": "thread", "data": json.dumps({"thread_id": thread_id})}
        async for ev in run_turn(body.message, thread_id, body.mode, body.timezone, body.locale):
            name, data = ev["event"], ev["data"]
            if name == "step":
                steps.setdefault(data["id"], {}).update(data)
            elif name == "plan":
                plan = data["todos"]
            elif name == "followups":
                followups = data["items"]
            elif name == "done":
                route = data.get("route") or {}
                done_steps = [{**st, "status": "failed", "detail": "stopped (time budget)"} if st.get("status") == "running" else st
                              for st in steps.values()]
                meta = {**data, "steps": done_steps, "plan": plan, "follow_ups": followups}
                meta.pop("answer", None)
                await db.add_message(thread_id, "assistant", data.get("answer", ""), meta)
                await db.update_thread(owner, thread_id, title=data.get("title"), scene=route.get("scene"))
            if await request.is_disconnected():
                logger.info("client disconnected from thread %s", thread_id)
                break
            yield {"event": name, "data": json.dumps(data, ensure_ascii=False, default=str)}

    return EventSourceResponse(events(), ping=15)
