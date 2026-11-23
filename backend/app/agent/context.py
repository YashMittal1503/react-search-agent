"""Per-run context shared by tools and nodes: source registry + event stream.

Tools are plain module-level LangChain tools; they find the active run through a ContextVar,
which LangGraph copies into every node/tool task it spawns.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid", "ref", "ref_src", "mc_cid", "mc_eid"}


def canonical_url(url: str) -> str:
    """Normalise a URL for de-duplication (keeps the exact URL for display separately)."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in _TRACKING])
    host = (p.hostname or "").lower().removeprefix("www.")
    path = p.path.rstrip("/") or "/"
    return urlunsplit(("https" if p.scheme in ("http", "https") else p.scheme, host, path, query, ""))


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


@dataclass
class Source:
    id: int
    url: str
    title: str
    domain: str
    snippet: str = ""
    published: str | None = None
    kind: str = "web"            # web | news | page | api
    fetched: bool = False         # full page content was read
    content: str = ""            # ranked excerpts the model saw (not sent to the UI)

    @property
    def favicon(self) -> str:
        return f"https://www.google.com/s2/favicons?domain={self.domain}&sz=64"

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("content")
        d["favicon"] = self.favicon
        return d


class SourceRegistry:
    """Every URL a tool returns gets a stable id ``S<n>``. The model cites ids, never URLs."""

    def __init__(self) -> None:
        self._by_id: dict[int, Source] = {}
        self._by_url: dict[str, int] = {}
        self._ids = itertools.count(1)

    def add(self, url: str, title: str = "", snippet: str = "", published: str | None = None, kind: str = "web") -> tuple[Source, bool]:
        key = canonical_url(url)
        if key in self._by_url:
            src = self._by_id[self._by_url[key]]
            if snippet and len(snippet) > len(src.snippet):
                src.snippet = snippet
            if title and not src.title:
                src.title = title
            if published and not src.published:
                src.published = published
            return src, False
        sid = next(self._ids)
        src = Source(id=sid, url=url, title=(title or domain_of(url))[:200], domain=domain_of(url),
                     snippet=snippet[:400], published=published, kind=kind)
        self._by_id[sid] = src
        self._by_url[key] = sid
        return src, True

    def get(self, sid: int) -> Source | None:
        return self._by_id.get(sid)

    def by_url(self, url: str) -> Source | None:
        sid = self._by_url.get(canonical_url(url))
        return self._by_id.get(sid) if sid else None

    def all(self) -> list[Source]:
        return list(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


@dataclass
class RunContext:
    question: str
    timezone: str = "UTC"
    locale: str = "en-US"
    mode: str = "auto"
    registry: SourceRegistry = field(default_factory=SourceRegistry)
    queue: asyncio.Queue | None = None
    started: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)
    widgets: list[dict[str, Any]] = field(default_factory=list)
    route: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=lambda: {"llm_calls": 0, "searches": 0, "fetches": 0})
    _step_ids: Any = field(default_factory=lambda: itertools.count(1))

    @property
    def now(self) -> datetime:
        try:
            return datetime.now(ZoneInfo(self.timezone))
        except Exception:
            return datetime.now(ZoneInfo("UTC"))

    def emit(self, event: str, data: dict[str, Any]) -> None:
        if self.queue is not None:
            self.queue.put_nowait({"event": event, "data": data})

    def step(self, kind: str, label: str, status: str = "running", **extra: Any) -> int:
        sid = next(self._step_ids)
        self.emit("step", {"id": sid, "kind": kind, "label": label, "status": status, **extra})
        return sid

    def step_update(self, sid: int, status: str, **extra: Any) -> None:
        self.emit("step", {"id": sid, "status": status, **extra})

    def register_source(self, src: Source, is_new: bool) -> None:
        if is_new:
            self.emit("source", src.public())

    def add_widget(self, widget: dict[str, Any]) -> None:
        self.widgets.append(widget)
        self.emit("widget", widget)


_current: ContextVar[RunContext | None] = ContextVar("run_context", default=None)


def current_run() -> RunContext:
    ctx = _current.get()
    if ctx is None:  # tools used outside a run (tests, notebooks)
        ctx = RunContext(question="")
        _current.set(ctx)
    return ctx


def set_run(ctx: RunContext):
    return _current.set(ctx)


def reset_run(token) -> None:
    _current.reset(token)
