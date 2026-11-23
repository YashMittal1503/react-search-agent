"""Site-specific handlers that use official/public APIs instead of scraping HTML.

APIs are faster, cleaner and more reliable than parsing these sites' HTML (and don't trip bot protection).
Each handler returns ``(text, title)``, or ``None`` if the URL isn't one it handles or the API failed, in which
case the waterfall moves on to generic fetching.
"""

from __future__ import annotations

import asyncio
import io
import re
from urllib.parse import parse_qs, unquote, urlsplit

import httpx


async def pdf_from_bytes(data: bytes, max_pages: int = 30) -> tuple[str, str] | None:
    """Convert a PDF (raw bytes) to markdown with pymupdf4llm, first ``max_pages`` pages only.

    Runs in a worker thread because PDF parsing is CPU-bound and would block the event loop.
    """

    def run():
        import pymupdf
        import pymupdf4llm

        doc = pymupdf.open(stream=io.BytesIO(data), filetype="pdf")
        title = (doc.metadata or {}).get("title") or ""
        md = pymupdf4llm.to_markdown(doc, pages=list(range(min(max_pages, doc.page_count))), show_progress=False)
        return md, title

    try:
        return await asyncio.to_thread(run)
    except Exception:
        return None


async def youtube(url: str, client: httpx.AsyncClient) -> tuple[str, str] | None:
    """YouTube video -> its transcript (watch, youtu.be, shorts, embed and live URLs); title via oEmbed."""
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    vid = None
    if host.endswith("youtu.be"):
        vid = p.path.strip("/").split("/")[0]
    elif "youtube.com" in host:
        vid = (parse_qs(p.query).get("v") or [None])[0]
        if not vid and p.path.startswith(("/shorts/", "/embed/", "/live/")):
            vid = p.path.split("/")[2]
    if not vid:
        return None

    def run():
        """Blocking transcript download (English preferred, Hindi as a fallback)."""
        from youtube_transcript_api import YouTubeTranscriptApi

        t = YouTubeTranscriptApi().fetch(vid, languages=["en", "en-US", "hi"])
        return " ".join(s.text for s in t)

    title = ""
    try:
        o = await client.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"})
        if o.status_code == 200:
            title = o.json().get("title", "")
    except Exception:
        pass
    try:
        text = await asyncio.to_thread(run)
    except Exception:
        return None
    return (f"Transcript of YouTube video: {title}\n\n{text}", title) if text else None


async def wikipedia(url: str, client: httpx.AsyncClient) -> tuple[str, str] | None:
    """Wikipedia / Wikivoyage article -> plain-text extract from the MediaWiki API (follows redirects)."""
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if not (host.endswith("wikipedia.org") or host.endswith("wikivoyage.org")) or not p.path.startswith("/wiki/"):
        return None
    title = unquote(p.path[len("/wiki/"):])
    r = await client.get(f"https://{host}/w/api.php", params={
        "action": "query", "prop": "extracts", "explaintext": 1, "titles": title, "format": "json", "redirects": 1,
    })
    if r.status_code != 200:
        return None
    pages = r.json().get("query", {}).get("pages", {})
    for page in pages.values():
        text = page.get("extract")
        if text:
            # MediaWiki "== Heading ==" -> markdown "## Heading", so chunking keeps sections together.
            text = re.sub(r"\n(=+) (.+?) \1\n", lambda m: "\n" + "#" * min(len(m.group(1)), 4) + " " + m.group(2) + "\n", text)
            return text, page.get("title", title)
    return None


async def reddit(url: str, client: httpx.AsyncClient) -> tuple[str, str] | None:
    """Reddit thread -> post text plus the top 25 comments with scores, via the public ``.json`` endpoint."""
    p = urlsplit(url)
    if "reddit.com" not in (p.hostname or "") or "/comments/" not in p.path:
        return None
    r = await client.get(f"https://www.reddit.com{p.path.rstrip('/')}.json", params={"limit": 30, "raw_json": 1})
    if r.status_code != 200:
        return None
    try:
        post = r.json()[0]["data"]["children"][0]["data"]
        comments = r.json()[1]["data"]["children"]
    except Exception:
        return None
    lines = [f"# {post.get('title', '')}", f"r/{post.get('subreddit')} · score {post.get('score')}", post.get("selftext", "")]
    for c in comments[:25]:
        d = c.get("data", {})
        if d.get("body"):
            lines.append(f"- ({d.get('score', 0)} pts) {d['body'][:800]}")
    return "\n\n".join(x for x in lines if x), post.get("title", "")


async def github(url: str, client: httpx.AsyncClient) -> tuple[str, str] | None:
    """GitHub repository root -> description, stars, language, last push and the raw README (REST API)."""
    p = urlsplit(url)
    if (p.hostname or "").lower() != "github.com":
        return None
    parts = [x for x in p.path.split("/") if x]
    if len(parts) != 2:          # only repo roots; files/issues fall through to generic fetching
        return None
    owner, repo = parts
    r = await client.get(f"https://api.github.com/repos/{owner}/{repo}/readme", headers={"Accept": "application/vnd.github.raw"})
    if r.status_code != 200:
        return None
    meta = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
    desc = ""
    if meta.status_code == 200:
        m = meta.json()
        desc = f"{m.get('description') or ''}\nStars: {m.get('stargazers_count')} · Language: {m.get('language')} · Updated: {m.get('pushed_at')}\n\n"
    return desc + r.text, f"{owner}/{repo}"


async def arxiv(url: str, client: httpx.AsyncClient) -> tuple[str, str] | None:
    """arXiv abs/pdf URL -> title, authors, date and abstract from the arXiv export API."""
    m = re.match(r"https?://arxiv\.org/(abs|pdf)/([\w.\-/]+?)(v\d+)?(\.pdf)?$", url)
    if not m:
        return None
    r = await client.get("http://export.arxiv.org/api/query", params={"id_list": m.group(2)})
    if r.status_code != 200:
        return None
    import feedparser

    e = (feedparser.parse(r.text).entries or [None])[0]
    if not e:
        return None
    authors = ", ".join(a.get("name", "") for a in e.get("authors", []))
    return f"# {e.title}\n\nAuthors: {authors}\nPublished: {e.get('published')}\n\n## Abstract\n{e.summary}", e.title


# Tried in order by the waterfall's "site_api" tier; each one returns None quickly for URLs it doesn't handle.
SITE_HANDLERS = [wikipedia, youtube, reddit, github, arxiv]
