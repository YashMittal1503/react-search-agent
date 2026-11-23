"""Search router: try providers in order, cache results, de-duplicate URLs.

The first provider that returns hits wins. A provider that errors is benched for a while (``_unhealthy``) so later
searches in the same process don't waste time on it: an hour for auth/credit errors, two minutes for rate
limits, 20 seconds for anything else. "Not configured" (no key) is not an error and doesn't bench anything.
"""

from __future__ import annotations

import logging
import time

from ...agent.context import canonical_url
from .. import cache
from .providers import NEWS_PROVIDERS, WEB_PROVIDERS, SearchError

logger = logging.getLogger(__name__)

# provider -> unhealthy until (after errors such as 429/432 "out of credits")
_unhealthy: dict[str, float] = {}


async def search(query: str, n: int = 8, recency_days: int | None = None, news: bool = False) -> tuple[list[dict], str]:
    """Search the web (or news) and return ``(hits, provider_used)``.

    Args:
        query: the search query.
        n: how many hits to ask each provider for.
        recency_days: only results from the last N days, where the provider supports it.
        news: use the news providers (news indexes, Google News RSS) instead of web search.

    Returns:
        Hits as ``{"url", "title", "snippet", "published", "provider"}`` dicts, de-duplicated by canonical URL, and
        the provider name (suffixed with " (cached)" for cache hits; ``"none"`` if every provider failed).
    """
    key = cache.make_key("search", query.lower().strip(), n, recency_days, news)
    cached = cache.get(key)
    if cached:
        return cached["hits"], cached["provider"] + " (cached)"

    providers = NEWS_PROVIDERS if news else WEB_PROVIDERS
    errors = []
    for name, fn in providers:
        if _unhealthy.get(name, 0) > time.time():
            continue
        try:
            hits = await fn(query, n, recency_days, news)
        except SearchError as err:      # not configured
            errors.append(str(err))
            continue
        except Exception as err:  # noqa: BLE001
            status = getattr(getattr(err, "response", None), "status_code", None)
            _unhealthy[name] = time.time() + (3600 if status in (401, 402, 403, 432) else 120 if status == 429 else 20)
            errors.append(f"{name}: {type(err).__name__} {status or ''} {str(err)[:120]}")
            logger.warning("search provider %s failed: %s", name, err)
            continue
        if hits:
            # Same page with different tracking params / trailing slash counts once.
            seen, unique = set(), []
            for h in hits:
                c = canonical_url(h["url"])
                if c not in seen:
                    seen.add(c)
                    unique.append(h)
            name = unique[0].get("provider", name)   # e.g. "ddgs:brave": the engine that actually answered
            # Fresh-news results go stale quickly (15 min); timeless searches are cached for 6 hours.
            cache.set(key, {"hits": unique, "provider": name}, ttl=900 if (news or recency_days) else 6 * 3600)
            return unique, name
        errors.append(f"{name}: no results")
    logger.warning("all search providers failed for %r: %s", query, errors)
    return [], "none"
