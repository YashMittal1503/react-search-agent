"""HTML -> clean markdown, a content-quality check, and query-focused chunk selection."""

from __future__ import annotations

import re

import trafilatura
from rank_bm25 import BM25Okapi

_BLOCK_PATTERNS = [
    r"enable javascript", r"javascript is (disabled|required)", r"checking (if the site connection is secure|your browser)",
    r"verify(ing)? you are (a )?human", r"are you a robot", r"captcha", r"access denied", r"request blocked",
    r"please enable cookies", r"attention required", r"just a moment\.\.\.", r"unusual traffic",
    r"subscribe to (continue|read)", r"sign in to (continue|read)", r"403 forbidden", r"page not found",
]
_BLOCK_RE = re.compile("|".join(_BLOCK_PATTERNS), re.IGNORECASE)


def html_to_markdown(html: str, url: str | None = None) -> tuple[str, str, str | None]:
    """Returns (markdown, title, published_date)."""
    text = trafilatura.extract(
        html, url=url, output_format="markdown", include_links=False, include_tables=True,
        include_comments=False, favor_recall=True, deduplicate=True,
    ) or ""
    title, date = "", None
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta:
            title = meta.title or ""
            date = meta.date
    except Exception:
        pass
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return text.strip(), title[:200], date


def quality(text: str) -> str:
    """ok | thin | blocked"""
    t = (text or "").strip()
    if len(t) < 200:
        return "blocked" if _BLOCK_RE.search(t) else "thin"
    head = t[:1500]
    if _BLOCK_RE.search(head) and len(t) < 2500:
        return "blocked"
    words = len(t.split())
    return "ok" if words >= 80 else "thin"


_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("the a an and or of to in on for is are was were be by with at from as that this it its what which who how when where why do does did i you we they".split())


def _tokens(s: str) -> list[str]:
    return [w for w in _WORD.findall(s.lower()) if w not in _STOP and len(w) > 1]


def chunk(text: str, target_chars: int = 900) -> list[str]:
    """Split markdown into ~target-sized chunks along paragraph boundaries, keeping headings attached."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf, heading = [], "", ""
    for p in paras:
        if p.startswith("#") and len(p) < 160:
            if buf:
                chunks.append(buf)
                buf = ""
            heading = p
            continue
        candidate = (buf + "\n\n" + p) if buf else ((heading + "\n" + p) if heading else p)
        if len(candidate) > target_chars and buf:
            chunks.append(buf)
            buf = (heading + "\n" + p) if heading else p
        else:
            buf = candidate
        while len(buf) > target_chars * 2:          # very long paragraph
            chunks.append(buf[: target_chars * 2])
            buf = buf[target_chars * 2:]
    if buf:
        chunks.append(buf)
    return chunks


def select_relevant(text: str, query: str, budget_tokens: int = 1200) -> str:
    """Pick the chunks most relevant to ``query`` (BM25) within a token budget; keep document order.
    The lead chunk is always kept because it usually holds the summary and the date."""
    budget_chars = budget_tokens * 4
    pieces = chunk(text, target_chars=max(250, min(900, budget_chars // 4)))   # several chunks must fit the budget
    if not pieces:
        return ""
    if sum(len(p) for p in pieces) <= budget_chars:
        return "\n\n".join(pieces)
    q = _tokens(query)
    corpus = [_tokens(p) or ["_"] for p in pieces]
    scores = BM25Okapi(corpus).get_scores(q) if q else [0.0] * len(pieces)
    order = sorted(range(1, len(pieces)), key=lambda i: scores[i], reverse=True)
    chosen, used = {0}, len(pieces[0])
    for i in order:
        if used + len(pieces[i]) > budget_chars:
            continue
        chosen.add(i)
        used += len(pieces[i])
    out, last = [], -1
    for i in sorted(chosen):
        if last != -1 and i != last + 1:
            out.append("[…]")
        out.append(pieces[i])
        last = i
    return "\n\n".join(out)
