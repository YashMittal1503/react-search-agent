"""Threads + messages for the UI (SQLite locally; any SQLAlchemy async URL, e.g. Postgres/Neon, later)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..settings import get_settings


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Thread(Base):
    __tablename__ = "threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    scene: Mapped[str] = mapped_column(String(32), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "pinned": self.pinned, "scene": self.scene,
                "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat()}


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_dict(self) -> dict:
        return {"id": self.id, "role": self.role, "content": self.content, "meta": self.meta or {},
                "created_at": self.created_at.isoformat()}


_engine = None
_session: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    global _engine, _session
    url = get_settings().database_url
    if url.startswith("sqlite"):
        Path(url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(url, pool_pre_ping=True)
    _session = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def session() -> AsyncSession:
    assert _session is not None, "init_db() not called"
    return _session()


async def list_threads(owner: str) -> list[dict]:
    async with session() as s:
        rows = (await s.execute(select(Thread).where(Thread.owner == owner).order_by(Thread.updated_at.desc()).limit(200))).scalars()
        return [t.to_dict() for t in rows]


async def get_thread(owner: str, thread_id: str) -> Thread | None:
    async with session() as s:
        t = await s.get(Thread, thread_id)
        return t if t and t.owner == owner else None


async def create_thread(owner: str, title: str = "New chat") -> dict:
    async with session() as s:
        t = Thread(owner=owner, title=title)
        s.add(t)
        await s.commit()
        return t.to_dict()


async def update_thread(owner: str, thread_id: str, **fields) -> dict | None:
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
    async with session() as s:
        m = Message(thread_id=thread_id, role=role, content=content, meta=meta or {})
        s.add(m)
        t = await s.get(Thread, thread_id)
        if t:
            t.updated_at = _now()
        await s.commit()
        return m.to_dict()


async def list_messages(thread_id: str) -> list[dict]:
    async with session() as s:
        rows = (await s.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))).scalars()
        return [m.to_dict() for m in rows]
