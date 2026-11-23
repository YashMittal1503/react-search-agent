"""Search providers. Each returns a list of normalised hits:
``{"url", "title", "snippet", "published", "provider"}``.

Order of preference (first that returns results wins, the rest are fallbacks):
  Tavily (1K free/mo) -> Exa ($10 free/mo) -> SearXNG (self-hosted, free) -> DuckDuckGo via ddgs (free).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import feedparser
import httpx

from ...settings import get_settings

logger = logging.getLogger(__name__)

# URL fragments of ad/redirect links some engines mix into results.
_AD_MARKERS = ("bing.com/aclick", "duckduckgo.com/y.js", "/aclk?", "doubleclick.net", "googleadservices")


def _hit(url: str, title: str, snippet: str, provider: str, published: str | None = None) -> dict[str, Any] | None:
    """Normalise one result into the common hit shape, or ``None`` for non-HTTP or ad URLs."""
    if not url or not url.startswith("http") or any(m in url for m in _AD_MARKERS):
        return None
    return {"url": url, "title": (title or "").strip(), "snippet": (snippet or "").strip()[:500],
            "published": published, "provider": provider}


class SearchError(RuntimeError):
    """Raised when a provider isn't configured (no key / URL). The router skips it without benching it."""


# ── Tavily ──────────────────────────────────────────────────────────────────
async def tavily(query: str, n: int, recency_days: int | None, news: bool) -> list[dict]:
    """Tavily search API: LLM-oriented results with clean snippets; best quality when a key is set."""
    key = get_settings().tavily_api_key
    if not key:
        raise SearchError("tavily: no key")
    body: dict[str, Any] = {"query": query, "max_results": n, "search_depth": "basic", "topic": "news" if news else "general"}
    if recency_days:
        # News topic takes a day count; general search only accepts day/week/month/year buckets.
        body["days" if news else "time_range"] = recency_days if news else ("day" if recency_days <= 1 else "week" if recency_days <= 7 else "month" if recency_days <= 31 else "year")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.tavily.com/search", json=body, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        data = r.json()
    return [h for h in (_hit(x.get("url"), x.get("title"), x.get("content"), "tavily", x.get("published_date")) for x in data.get("results", [])) if h]


# ── Exa ─────────────────────────────────────────────────────────────────────
async def exa(query: str, n: int, recency_days: int | None, news: bool) -> list[dict]:
    """Exa neural search; asks for 3-sentence highlights to use as snippets."""
    key = get_settings().exa_api_key
    if not key:
        raise SearchError("exa: no key")
    body: dict[str, Any] = {"query": query, "numResults": n, "type": "auto", "contents": {"highlights": {"numSentences": 3}}}
    if news:
        body["category"] = "news"
    if recency_days:
        from datetime import UTC, datetime, timedelta

        body["startPublishedDate"] = (datetime.now(UTC) - timedelta(days=recency_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with httpx.AsyncClient(timeout=25) as c:
        r = await c.post("https://api.exa.ai/search", json=body, headers={"x-api-key": key})
        r.raise_for_status()
        data = r.json()
    out = []
    for x in data.get("results", []):
        snippet = " ".join(x.get("highlights") or []) or x.get("text", "")[:400]
        h = _hit(x.get("url"), x.get("title"), snippet, "exa", x.get("publishedDate"))
        if h:
            out.append(h)
    return out


# ── SearXNG (self-hosted metasearch) ────────────────────────────────────────
async def searxng(query: str, n: int, recency_days: int | None, news: bool) -> list[dict]:
    """A self-hosted SearXNG instance (``docker compose up searxng``), queried through its JSON API."""
    base = get_settings().searxng_url
    if not base:
        raise SearchError("searxng: not configured")
    params: dict[str, Any] = {"q": query, "format": "json", "categories": "news" if news else "general"}
    if recency_days:
        params["time_range"] = "day" if recency_days <= 1 else "week" if recency_days <= 7 else "month" if recency_days <= 31 else "year"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(base.rstrip("/") + "/search", params=params)
        r.raise_for_status()
        data = r.json()
    return [h for h in (_hit(x.get("url"), x.get("title"), x.get("content"), "searxng", x.get("publishedDate")) for x in data.get("results", [])[:n]) if h]


# ── ddgs metasearch (no key): rotate engines, because each one throttles bursts differently ──
def _ddg_timelimit(days: int | None) -> str | None:
    """Map a day count to ddgs' timelimit codes: d(ay) / w(eek) / m(onth) / y(ear)."""
    if not days:
        return None
    return "d" if days <= 1 else "w" if days <= 7 else "m" if days <= 31 else "y"


_DDG_SLOTS = asyncio.Semaphore(2)          # at most 2 concurrent ddgs searches: bursts get throttled
# Engines tried in order. Each engine has its own throttling, so rotating keeps free search working under load.
_TEXT_BACKENDS = ["duckduckgo", "startpage", "brave", "yahoo", "mojeek", "auto", "wikipedia"]
_NEWS_BACKENDS = ["duckduckgo", "yahoo", "auto"]
_backend_cooldown: dict[str, float] = {}   # engine -> skip until (unix time), after it errored


async def duckduckgo(query: str, n: int, recency_days: int | None, news: bool) -> list[dict]:
    """Despite the name, this is the ddgs metasearch: DuckDuckGo first, then other engines."""
    import time as _time

    from ddgs import DDGS

    def run(backend: str, q: str) -> list[dict]:
        """Blocking ddgs call for one engine (run in a worker thread). "No results" is an empty list, not an error."""
        d = DDGS(timeout=10)
        try:
            if news:
                rows = d.news(q, max_results=n, timelimit=_ddg_timelimit(recency_days), backend=backend)
                return [h for h in (_hit(x.get("url"), x.get("title"), x.get("body"), f"ddgs:{backend}", x.get("date")) for x in rows) if h]
            rows = d.text(q, max_results=n + 4, timelimit=_ddg_timelimit(recency_days), backend=backend)
            return [h for h in (_hit(x.get("href"), x.get("title"), x.get("body"), f"ddgs:{backend}") for x in rows) if h][:n]
        except Exception as err:
            if "no results" in str(err).lower():
                return []
            raise

    queries = [query]
    if "site:" in query:  # engines often return nothing for site: filters; retry without
        queries.append(" ".join(w for w in query.split() if not w.startswith("site:")))
    async with _DDG_SLOTS:
        for q in queries:
            for backend in (_NEWS_BACKENDS if news else _TEXT_BACKENDS):
                if _backend_cooldown.get(backend, 0) > _time.time():
                    continue
                try:
                    hits = await asyncio.to_thread(run, backend, q)
                except Exception as err:  # noqa: BLE001
                    logger.info("ddgs backend %s failed: %s", backend, str(err)[:120])
                    _backend_cooldown[backend] = _time.time() + 60
                    continue
                if hits:
                    return hits
    return []


# ── Google News RSS (news fallback, no key) ─────────────────────────────────
async def google_news_rss(query: str, n: int, recency_days: int | None, news: bool = True) -> list[dict]:
    """Google News RSS search (no key). ``when:Nd`` restricts to recent articles; the publisher goes in the snippet."""
    q = query + (f" when:{recency_days}d" if recency_days else "")
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as c:
        r = await c.get("https://news.google.com/rss/search", params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        r.raise_for_status()
    feed = feedparser.parse(r.text)
    out = []
    for e in feed.entries[:n]:
        title = e.get("title", "")
        publisher = (e.get("source") or {}).get("title", "")
        h = _hit(e.get("link"), title, f"{publisher}: {title}" if publisher else title, "google_news", e.get("published"))
        if h:
            out.append(h)
    return out


# Fallback chains used by the search router (first one with results wins).
WEB_PROVIDERS = [("tavily", tavily), ("exa", exa), ("searxng", searxng), ("duckduckgo", duckduckgo)]
NEWS_PROVIDERS = [("tavily", tavily), ("exa", exa), ("duckduckgo", duckduckgo), ("google_news", google_news_rss), ("searxng", searxng)]
