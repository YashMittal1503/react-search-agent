"""Adaptive fetch waterfall.

    cache -> site API handler -> direct HTTP + trafilatura -> headless browser (crawl4ai, optional)
          -> Jina Reader -> Wayback Machine snapshot -> structured failure

Each tier's result passes a quality check (catches "enable JavaScript", bot walls and empty shells).
Per-domain stats remember which tier worked, so later fetches of that domain skip tiers that
keep failing there. No CAPTCHA solving or bot-detection evasion: when a site refuses, we use
public alternatives (archives, readers, other sources) and tell the agent to pick another source.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass

import httpx

from ...agent.context import domain_of
from ...settings import get_settings
from .. import cache
from .extract import html_to_markdown, quality
from .handlers import SITE_HANDLERS, pdf_from_bytes

logger = logging.getLogger(__name__)

TIERS = ["site_api", "http", "browser", "jina", "wayback"]   # default order (per-domain stats can reorder it)
MAX_BYTES = 6 * 1024 * 1024                                  # stop downloading after 6 MB (huge PDFs, media)


@dataclass
class FetchResult:
    """Outcome of fetching one URL. ``ok`` means some text came back; ``status`` says whether it's usable."""

    url: str
    ok: bool
    text: str = ""            # page content as markdown
    title: str = ""
    published: str | None = None
    tier: str = ""            # which tier produced it, e.g. "http", "http:pdf", "site_api:wikipedia", "jina"
    status: str = ""          # ok | thin | blocked | error | unsupported
    error: str = ""
    elapsed: float = 0.0      # seconds for the whole waterfall
    tried: list | None = None # "tier:status" for every tier attempted, in order (shown in timeline tooltips)

    def to_dict(self) -> dict:
        """Plain dict (for the cache)."""
        return asdict(self)


# ── per-domain learning + politeness ────────────────────────────────────────
# domain -> tier -> [successes, failures], persisted in the disk cache for 30 days.
_STATS_KEY = "fetch-domain-stats-v1"
# Politeness: at most 2 concurrent fetches per domain, however many the agent requests at once.
_domain_locks: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(2))


def _stats() -> dict:
    """All per-domain tier statistics."""
    return cache.get(_STATS_KEY) or {}


def _record(domain: str, tier: str, ok: bool) -> None:
    """Count one success or failure of ``tier`` on ``domain``."""
    stats = _stats()
    d = stats.setdefault(domain, {})
    s, f = d.get(tier, [0, 0])
    d[tier] = [s + ok, f + (not ok)]
    cache.set(_STATS_KEY, stats, ttl=30 * 24 * 3600)


def tier_order(domain: str) -> list[str]:
    """Skip tiers that failed >=2 times and never succeeded on this domain; try known-good tiers first."""
    d = _stats().get(domain, {})
    order = [t for t in TIERS if not (d.get(t, [0, 0])[0] == 0 and d.get(t, [0, 0])[1] >= 2)]
    order.sort(key=lambda t: -d.get(t, [0, 0])[0])
    # keep site_api first when it applies; it is cheap and returns clean text
    if "site_api" in order:
        order.remove("site_api")
        order.insert(0, "site_api")
    return order or TIERS


# ── tiers ───────────────────────────────────────────────────────────────────
def _headers() -> dict:
    """Browser-like request headers with an honest User-Agent that names the project."""
    return {
        "User-Agent": get_settings().user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
    }


async def _http(url: str, client: httpx.AsyncClient) -> FetchResult:
    """Direct GET (HTTP/2): HTML -> trafilatura markdown, PDF -> pymupdf4llm, plain text as is.

    The body is streamed and capped at ``MAX_BYTES``. Binary content types are reported as ``unsupported``.
    """
    async with client.stream("GET", url) as r:
        if r.status_code >= 400:
            return FetchResult(url, False, tier="http", status="blocked" if r.status_code in (401, 403, 429, 451) else "error",
                               error=f"HTTP {r.status_code}")
        ctype = r.headers.get("content-type", "").lower()
        body = b""
        async for part in r.aiter_bytes():
            body += part
            if len(body) > MAX_BYTES:
                break
    # Servers often mislabel PDFs, so also trust the extension and the "%PDF-" magic bytes.
    if "pdf" in ctype or url.lower().endswith(".pdf") or body[:5] == b"%PDF-":
        res = await pdf_from_bytes(body)
        if not res:
            return FetchResult(url, False, tier="http", status="error", error="pdf parse failed")
        text, title = res
        return FetchResult(url, True, text=text, title=title, tier="http:pdf", status=quality(text))
    if not any(t in ctype for t in ("html", "xml", "text")) and ctype:
        return FetchResult(url, False, tier="http", status="unsupported", error=f"content-type {ctype}")
    html = body.decode(r.encoding or "utf-8", errors="replace")
    if "text/plain" in ctype:
        return FetchResult(url, True, text=html, tier="http", status=quality(html))
    text, title, date = html_to_markdown(html, url)
    return FetchResult(url, True, text=text, title=title, published=date, tier="http", status=quality(text))


async def _browser(url: str) -> FetchResult:
    """Render the page in headless Chromium via crawl4ai (optional tier, for JS-rendered sites).

    Disabled unless ``ENABLE_BROWSER_FETCH=true`` and crawl4ai is installed; then it reports ``unsupported`` and the
    waterfall skips it without counting a failure.
    """
    if not get_settings().enable_browser_fetch:
        return FetchResult(url, False, tier="browser", status="unsupported", error="browser tier disabled")
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError:
        return FetchResult(url, False, tier="browser", status="unsupported", error="crawl4ai not installed")
    cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=25000, wait_until="networkidle",
                           scan_full_page=True, remove_overlay_elements=True)
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False, user_agent=get_settings().user_agent)) as crawler:
        r = await crawler.arun(url=url, config=cfg)
    if not r.success:
        return FetchResult(url, False, tier="browser", status="error", error=(r.error_message or "")[:200])
    html = r.html or ""
    text, title, date = html_to_markdown(html, url) if html else ("", "", None)
    if len(text) < 300:          # trafilatura found little: fall back to crawl4ai's own markdown conversion
        md = r.markdown
        text = (getattr(md, "fit_markdown", None) or getattr(md, "raw_markdown", None) or str(md or "")).strip()
    return FetchResult(url, True, text=text, title=title, published=date, tier="browser", status=quality(text))


async def _jina(url: str, client: httpx.AsyncClient) -> FetchResult:
    """Jina Reader (``r.jina.ai/<url>``): a public service that renders a page and returns markdown."""
    headers = {"X-Return-Format": "markdown", "Accept": "text/plain"}
    if key := get_settings().jina_api_key:
        headers["Authorization"] = f"Bearer {key}"
    r = await client.get(f"https://r.jina.ai/{url}", headers=headers, timeout=30)
    if r.status_code != 200:
        return FetchResult(url, False, tier="jina", status="error", error=f"HTTP {r.status_code}")
    text = r.text
    title = ""
    # Jina's response starts with "Title: ...", "URL Source: ...", then "Markdown Content:" and the page.
    if text.startswith("Title:"):
        title = text.split("\n", 1)[0][6:].strip()
    if "Markdown Content:" in text:
        text = text.split("Markdown Content:", 1)[1]
    text = text.strip()
    return FetchResult(url, True, text=text, title=title, tier="jina", status=quality(text))


async def _wayback(url: str, client: httpx.AsyncClient) -> FetchResult:
    """The closest Internet Archive snapshot, labelled with its date so the model knows it may be outdated."""
    r = await client.get("https://archive.org/wayback/available", params={"url": url}, timeout=15)
    snap = (r.json().get("archived_snapshots") or {}).get("closest") if r.status_code == 200 else None
    if not snap or not snap.get("available"):
        return FetchResult(url, False, tier="wayback", status="error", error="no snapshot")
    ts = snap["timestamp"]
    raw = snap["url"].replace(f"/{ts}/", f"/{ts}id_/", 1)   # id_ = original page without the toolbar
    res = await _http(raw, client)
    res.url, res.tier = url, "wayback"
    if res.ok:
        res.text = f"(Archived copy from {ts[:4]}-{ts[4:6]}-{ts[6:8]}; may be outdated.)\n\n{res.text}"
    return res


async def _site_api(url: str, client: httpx.AsyncClient) -> FetchResult:
    """Try each site-specific API handler; ``unsupported`` when none of them handles this URL."""
    for handler in SITE_HANDLERS:
        try:
            res = await handler(url, client)
        except Exception as err:  # noqa: BLE001
            logger.info("site handler %s failed for %s: %s", handler.__name__, url, err)
            continue
        if res:
            text, title = res
            return FetchResult(url, True, text=text, title=title, tier=f"site_api:{handler.__name__}", status=quality(text))
    return FetchResult(url, False, tier="site_api", status="unsupported")


# ── SSRF guard ──────────────────────────────────────────────────────────────
def is_private_url(url: str) -> bool:
    """True for localhost / private / link-local targets (incl. hostnames that resolve to them).

    The agent fetches URLs that came from search results or the user, so without this a prompt could make the
    server fetch internal addresses (cloud metadata at 169.254.169.254, a router admin page...). Hostnames that
    don't resolve are not private; the fetch will just fail normally.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return True
    try:
        addrs = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addrs = {ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(host, None)}
        except OSError:
            return False
    return any(a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast for a in addrs)


# ── orchestrator ────────────────────────────────────────────────────────────
async def fetch(url: str, use_cache: bool = True) -> FetchResult:
    """Fetch ``url`` through the waterfall and return the best result.

    Stops at the first tier whose text passes the quality check. If no tier gives ``ok`` text, the longest
    ``thin`` result is returned (some text beats none); otherwise a structured failure listing every tier tried,
    so the agent can say "blocked" and choose another source. Successful results are cached for 6 hours.
    """
    t0 = time.perf_counter()
    if not url.lower().startswith(("http://", "https://")):
        return FetchResult(url, False, status="unsupported", error="only http(s) URLs can be fetched")
    if not get_settings().allow_private_fetch and await asyncio.to_thread(is_private_url, url):
        return FetchResult(url, False, status="blocked", error="refused: private or local network address")
    key = cache.make_key("fetch", url)
    if use_cache and (hit := cache.get(key)):
        res = FetchResult(**hit)
        res.tier += " (cached)"
        return res

    domain = domain_of(url)
    tried: list[str] = []
    best: FetchResult | None = None
    async with _domain_locks[domain], httpx.AsyncClient(
        http2=True, follow_redirects=True, timeout=get_settings().fetch_timeout, headers=_headers(),
    ) as client:
        for tier in tier_order(domain):
            try:
                if tier == "site_api":
                    res = await _site_api(url, client)
                    if res.status == "unsupported":    # not a Wikipedia/YouTube/... URL: not a failure
                        continue
                elif tier == "http":
                    res = await _http(url, client)
                elif tier == "browser":
                    res = await _browser(url)
                    if res.status == "unsupported":
                        continue
                elif tier == "jina":
                    res = await _jina(url, client)
                else:
                    res = await _wayback(url, client)
            except Exception as err:  # noqa: BLE001
                res = FetchResult(url, False, tier=tier, status="error", error=f"{type(err).__name__}: {str(err)[:160]}")
            tried.append(f"{res.tier}:{res.status or 'error'}")
            good = res.ok and res.status == "ok"
            if tier != "site_api" or res.ok:   # a site API "not applicable" shouldn't count against the domain
                _record(domain, tier, good)
            if good:
                best = res
                break
            if res.ok and res.status == "thin" and (best is None or len(res.text) > len(best.text)):
                best = res
            if res.status == "unsupported" and tier == "http":
                break  # binary content (images, zips): no other tier will help

    if best is None:
        best = FetchResult(url, False, status="blocked" if any("blocked" in t for t in tried) else "error",
                           error="all fetch tiers failed: " + ", ".join(tried))
    best.tried = tried
    best.elapsed = round(time.perf_counter() - t0, 2)
    if best.ok:
        cache.set(key, best.to_dict(), ttl=6 * 3600)
    return best
