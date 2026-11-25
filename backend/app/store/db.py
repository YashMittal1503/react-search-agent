"""Threads + messages for the UI (SQLite locally; any SQLAlchemy async URL, e.g. Postgres/Neon, later)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..settings import get_settings


def _now() -> datetime:
    """Timezone-aware UTC now (stored with every row)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for the two tables below."""


class Thread(Base):
    """A chat thread in the sidebar. ``owner`` is the anonymous browser id (X-Client-Id); there are no accounts.

    The thread id doubles as the LangGraph ``thread_id``, so the agent's memory and the UI history line up.
    """

    __tablename__ = "threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    scene: Mapped[str] = mapped_column(String(32), default="default")    # last scene, restored when reopened
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    def to_dict(self) -> dict:
        """JSON shape returned by the threads API."""
        return {"id": self.id, "title": self.title, "pinned": self.pinned, "scene": self.scene,
                "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat()}


class Message(Base):
    """One user or assistant message, as displayed in the UI.

    ``meta`` holds everything needed to re-render an assistant answer after a reload: cited and all sources,
    timeline steps, plan, widgets, route and follow-ups.
    """

    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))          # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_dict(self) -> dict:
        """JSON shape returned by the messages API."""
        return {"id": self.id, "role": self.role, "content": self.content, "meta": self.meta or {},
                "created_at": self.created_at.isoformat()}


class TokenUsage(Base):
    """Token use of one run on one provider/model: one row per (run, provider, model).

    ``run_id`` is the agent turn's id (also its LangSmith trace id), so a row can be matched to its trace.
    ``source`` tells chat traffic from eval runs, if evals are ever pointed at this database. There is no foreign
    key to threads: usage is kept as an audit trail even after a thread is deleted.
    """

    __tablename__ = "token_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="chat")      # chat | eval
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)   # quick | deep (the route taken)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(128))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_calls: Mapped[int] = mapped_column(Integer, default=0)     # calls whose tokens are estimates
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


_engine = None
_session: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Create the engine and session factory and make sure the tables exist (called at app startup)."""
    global _engine, _session
    url = get_settings().database_url
    if url.startswith("sqlite"):          # SQLite won't create the folder of its database file
        Path(url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(url, pool_pre_ping=True)
    _session = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def session() -> AsyncSession:
    """A new async session; use as ``async with session() as s:``."""
    assert _session is not None, "init_db() not called"
    return _session()


async def list_threads(owner: str) -> list[dict]:
    """The owner's 200 most recently active threads, newest first."""
    async with session() as s:
        rows = (await s.execute(select(Thread).where(Thread.owner == owner).order_by(Thread.updated_at.desc()).limit(200))).scalars()
        return [t.to_dict() for t in rows]


async def get_thread(owner: str, thread_id: str) -> Thread | None:
    """A thread, only if it belongs to ``owner`` (so one browser can't read another's chats)."""
    async with session() as s:
        t = await s.get(Thread, thread_id)
        return t if t and t.owner == owner else None


async def create_thread(owner: str, title: str = "New chat") -> dict:
    """Create an empty thread and return it."""
    async with session() as s:
        t = Thread(owner=owner, title=title)
        s.add(t)
        await s.commit()
        return t.to_dict()


async def update_thread(owner: str, thread_id: str, **fields) -> dict | None:
    """Set ``title`` / ``pinned`` / ``scene`` (``None`` values are ignored) and bump ``updated_at``.

    Returns:
        The updated thread, or ``None`` if it doesn't exist or isn't the owner's.
    """
    async with session() as s:
        t = await s.get(Thread, thread_id)
        if not t or t.owner != owner:
            return None
        for k, v in fields.items():
            if v is not None and k in ("title", "pinned", "scene"):
                setattr(t, k, v)
        t.updated_at = _now()
        await s.commit()
        return t.to_dict()


async def delete_thread(owner: str, thread_id: str) -> bool:
    """Delete a thread and its messages (explicitly, since SQLite doesn't enforce cascades by default)."""
    async with session() as s:
        t = await s.get(Thread, thread_id)
        if not t or t.owner != owner:
            return False
        for m in (await s.execute(select(Message).where(Message.thread_id == thread_id))).scalars():
            await s.delete(m)
        await s.delete(t)
        await s.commit()
        return True


async def add_message(thread_id: str, role: str, content: str, meta: dict | None = None) -> dict:
    """Append a message and mark the thread as recently active (it moves to the top of the sidebar)."""
    async with session() as s:
        m = Message(thread_id=thread_id, role=role, content=content, meta=meta or {})
        s.add(m)
        t = await s.get(Thread, thread_id)
        if t:
            t.updated_at = _now()
        await s.commit()
        return m.to_dict()


async def list_messages(thread_id: str) -> list[dict]:
    """All messages of a thread in chronological order (ownership is checked by the caller)."""
    async with session() as s:
        rows = (await s.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))).scalars()
        return [m.to_dict() for m in rows]


_COUNTERS = ("calls", "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens", "total_tokens", "estimated_calls")


async def add_token_usage(run_id: str, thread_id: str | None, tokens: dict | None, source: str = "chat",
                          mode: str | None = None) -> int:
    """Store a run's token summary (``usage.tokens`` from the ``done`` event) as one row per provider/model.

    Returns:
        The number of rows written (0 when the run made no model calls, e.g. a failed turn).
    """
    rows = (tokens or {}).get("by_model") or []
    if not rows:
        return 0
    async with session() as s:
        for r in rows:
            s.add(TokenUsage(run_id=run_id, thread_id=thread_id, source=source, mode=mode,
                             provider=r.get("provider", "unknown"), model=r.get("model", "unknown"),
                             **{k: int(r.get(k) or 0) for k in _COUNTERS}))
        await s.commit()
    return len(rows)


async def usage_for_run(run_id: str) -> list[dict]:
    """All provider/model rows of one run."""
    async with session() as s:
        rows = (await s.execute(select(TokenUsage).where(TokenUsage.run_id == run_id))).scalars()
        return [{"provider": r.provider, "model": r.model, **{k: getattr(r, k) for k in _COUNTERS}} for r in rows]


async def usage_summary(days: int = 7, source: str | None = None) -> dict:
    """Token use per provider/model over the last ``days`` days (for ``GET /api/usage``).

    Returns:
        ``{"days", "runs", "totals": {...counters}, "by_model": [{"provider", "model", "runs", ...counters}]}``,
        ``by_model`` sorted by total tokens.
    """
    from datetime import timedelta

    since = _now() - timedelta(days=days)
    cols = [func.sum(getattr(TokenUsage, k)).label(k) for k in _COUNTERS]
    async with session() as s:
        q = select(TokenUsage.provider, TokenUsage.model, func.count(func.distinct(TokenUsage.run_id)).label("runs"), *cols)
        q = q.where(TokenUsage.created_at >= since)
        if source:
            q = q.where(TokenUsage.source == source)
        result = (await s.execute(q.group_by(TokenUsage.provider, TokenUsage.model))).all()
        runs_q = select(func.count(func.distinct(TokenUsage.run_id))).where(TokenUsage.created_at >= since)
        if source:
            runs_q = runs_q.where(TokenUsage.source == source)
        runs = (await s.execute(runs_q)).scalar() or 0
    by_model = [{"provider": r.provider, "model": r.model, "runs": r.runs, **{k: int(getattr(r, k) or 0) for k in _COUNTERS}}
                for r in result]
    by_model.sort(key=lambda r: r["total_tokens"], reverse=True)
    totals = {k: sum(r[k] for r in by_model) for k in _COUNTERS}
    return {"days": days, "runs": runs, "totals": totals, "by_model": by_model}
