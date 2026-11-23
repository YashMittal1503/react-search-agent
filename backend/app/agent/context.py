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

# Query parameters that only track clicks; dropped when deciding whether two URLs are the same page.
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
    """Lower-cased host without ``www.`` (``https://www.BBC.co.uk/x`` -> ``bbc.co.uk``)."""
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


@dataclass
class Source:
    """One web page or API result the agent has seen during a run."""

    id: int                      # the S<n> id the model cites
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
        """Favicon URL for the UI's source cards (Google's public favicon service)."""
        return f"https://www.google.com/s2/favicons?domain={self.domain}&sz=64"

    def public(self) -> dict[str, Any]:
        """The source as sent to the browser: everything except the (large) excerpt text, plus the favicon."""
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
        """Register a URL, or return the existing source if the same page (after canonicalisation) is known.

        When a known page is seen again, missing metadata is filled in and a longer snippet replaces a shorter one.

        Returns:
            ``(source, is_new)``.
        """
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
        """Source by id, or ``None`` (used by the citation guard to reject made-up ids)."""
        return self._by_id.get(sid)

    def by_url(self, url: str) -> Source | None:
        """Source for a URL (canonicalised), or ``None``."""
        sid = self._by_url.get(canonical_url(url))
        return self._by_id.get(sid) if sid else None

    def all(self) -> list[Source]:
        """All sources in id order."""
        return list(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


@dataclass
class RunContext:
    """Everything that belongs to one chat turn: its sources, the UI event queue and bookkeeping.

    Created by ``runner.run_turn`` and made available to graph nodes and tools through :func:`current_run`.
    """

    question: str
    timezone: str = "UTC"                    # the user's IANA timezone (from the browser)
    locale: str = "en-US"
    mode: str = "auto"                       # auto | quick | deep (UI toggle)
    registry: SourceRegistry = field(default_factory=SourceRegistry)
    queue: asyncio.Queue | None = None       # events for the SSE stream; None = nobody listening (tests)
    started: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)              # research notes from each agent run
    widgets: list[dict[str, Any]] = field(default_factory=list) # weather/news cards sent with the answer
    route: dict[str, Any] = field(default_factory=dict)         # router output, later also cited sources + title
    usage: dict[str, int] = field(default_factory=lambda: {"llm_calls": 0, "searches": 0, "fetches": 0})
    _step_ids: Any = field(default_factory=lambda: itertools.count(1))   # ids for timeline steps

    @property
    def now(self) -> datetime:
        """Current time in the user's timezone (falls back to UTC for an unknown zone name)."""
        try:
            return datetime.now(ZoneInfo(self.timezone))
        except Exception:
            return datetime.now(ZoneInfo("UTC"))

    def emit(self, event: str, data: dict[str, Any]) -> None:
        """Queue an SSE event (``event`` name + JSON-able ``data``) for the browser. Never blocks."""
        if self.queue is not None:
            self.queue.put_nowait({"event": event, "data": data})

    def step(self, kind: str, label: str, status: str = "running", **extra: Any) -> int:
        """Add a line to the UI's research timeline (search / fetch / weather / think / write).

        Returns:
            The step id, to pass to :meth:`step_update` when the step finishes or fails.
        """
        sid = next(self._step_ids)
        self.emit("step", {"id": sid, "kind": kind, "label": label, "status": status, **extra})
        return sid

    def step_update(self, sid: int, status: str, **extra: Any) -> None:
        """Update a timeline step (e.g. ``done`` with the tier that worked, or ``failed`` with a reason)."""
        self.emit("step", {"id": sid, "status": status, **extra})

    def register_source(self, src: Source, is_new: bool) -> None:
        """Tell the UI about a newly discovered source (so the sources strip fills in live)."""
        if is_new:
            self.emit("source", src.public())

    def add_widget(self, widget: dict[str, Any]) -> None:
        """Attach a rich card (weather, news) to the answer and stream it immediately."""
        self.widgets.append(widget)
        self.emit("widget", widget)


# The active run. asyncio copies ContextVars into child tasks, so tools running inside LangGraph see it too.
_current: ContextVar[RunContext | None] = ContextVar("run_context", default=None)


def current_run() -> RunContext:
    """The RunContext of the turn being processed (a throwaway one outside a run, e.g. in tests)."""
    ctx = _current.get()
    if ctx is None:  # tools used outside a run (tests, notebooks)
        ctx = RunContext(question="")
        _current.set(ctx)
    return ctx


def set_run(ctx: RunContext):
    """Make ``ctx`` the active run; returns a token for :func:`reset_run`."""
    return _current.set(ctx)


def reset_run(token) -> None:
    """Restore whatever run was active before :func:`set_run`."""
    _current.reset(token)
