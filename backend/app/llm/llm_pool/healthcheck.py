"""Ping every configured (provider, model) once and report which ones are alive.

    python -m llm_pool.healthcheck --config models.yaml [--tier agent] [--tools]
"""

from __future__ import annotations

import argparse
import asyncio
import time

from .config import PoolConfig
from .errors import classify_error
from .router import LLMRouter

_TOOL = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Get the current time in a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}


async def _probe(router: LLMRouter, target, tools: bool) -> tuple[str, str, float, str]:
    pool = router.pools[target.provider]
    slot = pool.slots[0]
    spec = router.config.providers[target.provider]
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=slot.key, base_url=spec.base_url, max_retries=0, timeout=45,
                         default_headers=spec.headers or None)
    t0 = time.perf_counter()
    try:
        kwargs = dict(model=target.model, max_tokens=64, temperature=0,
                      messages=[{"role": "user", "content": "What time is it in Paris? Use the tool." if tools else "Reply with: ok"}])
        if tools:
            kwargs["tools"] = [_TOOL]
        resp = await client.chat.completions.create(**kwargs, **target.params)
        msg = resp.choices[0].message
        detail = "tool_call" if getattr(msg, "tool_calls", None) else (msg.content or "").strip()[:30]
        if tools and not getattr(msg, "tool_calls", None):
            return target.id, "NO_TOOL_CALL", time.perf_counter() - t0, detail
        return target.id, "OK", time.perf_counter() - t0, detail
    except Exception as err:  # noqa: BLE001
        return target.id, classify_error(err).value.upper(), time.perf_counter() - t0, str(err)[:90]


async def main_async(config: str, tier: str | None, tools: bool) -> int:
    router = LLMRouter(PoolConfig.from_yaml(config))
    print("keys:", {k: v for k, v in router.key_counts().items() if v})
    tiers = [tier] if tier else list(router.config.tiers)
    seen, targets = set(), []
    for t in tiers:
        for target in router.targets(t):
            if target.id not in seen:
                seen.add(target.id)
                targets.append(target)
    results = await asyncio.gather(*(_probe(router, t, tools) for t in targets))
    width = max((len(r[0]) for r in results), default=10)
    bad = 0
    for tid, status, secs, detail in results:
        bad += status != "OK"
        print(f"{tid:<{width}}  {status:<18} {secs:5.1f}s  {detail}")
    return 1 if bad == len(results) else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="models.yaml")
    ap.add_argument("--tier")
    ap.add_argument("--tools", action="store_true", help="check tool calling instead of plain chat")
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    raise SystemExit(asyncio.run(main_async(args.config, args.tier, args.tools)))


if __name__ == "__main__":
    main()
