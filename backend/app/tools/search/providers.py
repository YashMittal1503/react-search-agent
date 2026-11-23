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

_AD_MARKERS = ("bing.com/aclick", "duckduckgo.com/y.js", "/aclk?", "doubleclick.net", "googleadservices")


def _hit(url: str, title: str, snippet: str, provider: str, published: str | None = None) -> dict[str, Any] | None:
    if not url or not url.startswith("http") or any(m in url for m in _AD_MARKERS):
        return None
    return {"url": url, "title": (title or "").strip(), "snippet": (snippet or "").strip()[:500],
            "published": published, "provider": provider}


class SearchError(RuntimeError):
    pass


# ── Tavily ──────────────────────────────────────────────────────────────────
async def tavily(query: str, n: int, recency_days: int | None, news: bool) -> list[dict]:
    key = get_settings().tavily_api_key
    if not key:
        raise SearchError("tavily: no key")
    body: dict[str, Any] = {"query": query, "max_results": n, "search_depth": "basic", "topic": "news" if news else "general"}
    if recency_days:
        body["days" if news else "time_range"] = recency_days if news else ("day" if recency_days <= 1 else "week" if recency_days <= 7 else "month" if recency_days <= 31 else "year")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.tavily.com/search", json=body, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        data = r.json()
    return [h for h in (_hit(x.get("url"), x.get("title"), x.get("content"), "tavily", x.get("published_date")) for x in data.get("results", [])) if h]


# ── Exa ─────────────────────────────────────────────────────────────────────
async def exa(query: str, n: int, recency_days: int | None, news: bool) -> list[dict]:
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


# ── DuckDuckGo (ddgs, no key) ───────────────────────────────────────────────
def _ddg_timelimit(days: int | None) -> str | None:
    if not days:
        return None
    return "d" if days <= 1 else "w" if days <= 7 else "m" if days <= 31 else "y"


async def duckduckgo(query: str, n: int, recency_days: int | None, news: bool) -> list[dict]:
    from ddgs import DDGS

    def run() -> list[dict]:
        try:
            return _run()
        except Exception as err:  # ddgs raises when a query simply has no hits
            if "no results" in str(err).lower():
                return []
            raise

    def _run() -> list[dict]:
        d = DDGS(timeout=12)
        if news:
            rows = d.news(query, max_results=n, timelimit=_ddg_timelimit(recency_days))
            return [h for h in (_hit(x.get("url"), x.get("title"), x.get("body"), "duckduckgo", x.get("date")) for x in rows) if h]
        rows = d.text(query, max_results=n + 3, timelimit=_ddg_timelimit(recency_days))
        return [h for h in (_hit(x.get("href"), x.get("title"), x.get("body"), "duckduckgo") for x in rows) if h][:n]

    return await asyncio.to_thread(run)


# ── Google News RSS (news fallback, no key) ─────────────────────────────────
async def google_news_rss(query: str, n: int, recency_days: int | None, news: bool = True) -> list[dict]:
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


WEB_PROVIDERS = [("tavily", tavily), ("exa", exa), ("searxng", searxng), ("duckduckgo", duckduckgo)]
NEWS_PROVIDERS = [("tavily", tavily), ("exa", exa), ("duckduckgo", duckduckgo), ("google_news", google_news_rss), ("searxng", searxng)]
