"""Scraper benchmark: how often does the fetch waterfall get usable text, from which tier, how fast?

    uv run python -m evals scrape-bench
"""

from __future__ import annotations

import asyncio
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime

from app.tools.fetch.waterfall import fetch

from .runner import REPORTS

# Real public URLs grouped by the kind of page they represent. Some are expected to fail (paywalls, logins):
# the benchmark measures honestly how often the waterfall gets usable text without any evasion.
URLS: dict[str, list[str]] = {
    "static_article": [
        "https://en.wikipedia.org/wiki/ReAct_(machine_learning)",
        "https://www.bbc.com/news/science-environment",
        "https://www.theguardian.com/technology",
        "https://docs.python.org/3/tutorial/index.html",
        "https://www.nasa.gov/missions/artemis/",
        "https://www.who.int/news-room/fact-sheets/detail/malaria",
    ],
    "news": [
        "https://apnews.com/hub/technology",
        "https://www.reuters.com/technology/",
        "https://www.aljazeera.com/news/",
        "https://timesofindia.indiatimes.com/india",
        "https://techcrunch.com/",
    ],
    "js_heavy_spa": [
        "https://www.airbnb.com/s/Kyoto/homes",
        "https://www.booking.com/city/jp/kyoto.html",
        "https://x.com/NASA",
        "https://www.instagram.com/natgeo/",
        "https://www.figma.com/community",
    ],
    "docs_dev": [
        "https://github.com/langchain-ai/deepagents",
        "https://fastapi.tiangolo.com/tutorial/",
        "https://react.dev/learn",
        "https://arxiv.org/abs/2210.03629",
        "https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python",
    ],
    "pdf": [
        "https://arxiv.org/pdf/2210.03629",
        "https://arxiv.org/pdf/1706.03762",
    ],
    "forum_video": [
        "https://www.reddit.com/r/Python/comments/1b5pz1l/what_are_some_good_python_projects_for_beginners/",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://news.ycombinator.com/",
    ],
    "travel_commerce": [
        "https://www.japan-guide.com/e/e2158.html",
        "https://kyoto.travel/en/",
        "https://www.lonelyplanet.com/japan/kansai/kyoto",
        "https://www.tripadvisor.com/Tourism-g298564-Kyoto_Kyoto_Prefecture_Kinki-Vacations.html",
        "https://www.amazon.com/dp/B0D1XD1ZV3",
    ],
    "paywalled": [
        "https://www.nytimes.com/section/technology",
        "https://www.wsj.com/tech",
        "https://www.ft.com/technology",
        "https://www.economist.com/science-and-technology",
    ],
}


async def bench() -> None:
    """Fetch every URL (cache off, 4 at a time), print one line per URL, and write JSON + markdown reports."""
    rows = []
    sem = asyncio.Semaphore(4)

    async def one(cat: str, url: str):
        """Fetch one URL and record whether it produced quality text, from which tier and how fast."""
        async with sem:
            r = await fetch(url, use_cache=False)
        good = r.ok and r.status == "ok"
        rows.append({"category": cat, "url": url, "ok": good, "status": r.status, "tier": r.tier, "chars": len(r.text),
                     "seconds": r.elapsed, "tried": r.tried})
        print(f"{'OK ' if good else 'BAD'} {cat:<16} {r.tier or '-':<22} {r.elapsed:>5}s {len(r.text):>7} chars  {url}")

    await asyncio.gather(*(one(c, u) for c, us in URLS.items() for u in us))
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    tiers = Counter(r["tier"].split(":")[0] for r in rows if r["ok"])   # "site_api:wikipedia" -> "site_api"
    summary = {
        "urls": len(rows),
        "success_rate": round(sum(r["ok"] for r in rows) / len(rows), 3),
        "median_seconds": statistics.median(r["seconds"] for r in rows),
        "winning_tier": dict(tiers),
        "by_category": {c: round(sum(r["ok"] for r in rs) / len(rs), 2) for c, rs in sorted(by_cat.items())},
    }
    print(json.dumps(summary, indent=2))
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (REPORTS / f"scrape-bench-{stamp}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    md = ["# Scraper benchmark", "", f"Success **{summary['success_rate']}** on {summary['urls']} URLs · median {summary['median_seconds']}s",
          "", "| Category | success |", "|---|---|"] + [f"| {c} | {v} |" for c, v in summary["by_category"].items()]
    md += ["", "Winning tier counts: " + ", ".join(f"{k} {v}" for k, v in tiers.most_common())]
    (REPORTS / "scrape-bench-latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> None:
    """Entry point for ``python -m evals scrape-bench``."""
    asyncio.run(bench())
