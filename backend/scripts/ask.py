"""Ask the agent from the terminal and watch the event stream.

    uv run python -m scripts.ask "What's the weather in Mumbai today?" [--mode quick|deep] [--tz Asia/Kolkata]
"""

import argparse
import asyncio
import json
import sys

from app.agent.runner import run_turn
from app.observability import flush_traces, setup_observability


async def main(q: str, mode: str, tz: str, raw: bool) -> None:
    """Run one turn and pretty-print its events (``raw`` prints every event as JSON instead)."""
    async for ev in run_turn(q, None, mode, tz):
        name, data = ev["event"], ev["data"]
        if raw:
            print(name, json.dumps(data, default=str)[:300])
        elif name == "token":
            sys.stdout.write(data["text"])
            sys.stdout.flush()
        elif name == "step":
            print(f"  · {data.get('kind', '')} {data.get('label', '')} [{data.get('status')}] {data.get('tier', '') or data.get('provider', '')}")
        elif name in ("route", "scene", "plan", "notice", "error"):
            print(f"  [{name}] {json.dumps(data, default=str)[:240]}")
        elif name == "done":
            print("\n\n--- sources ---")
            for s in data["sources"]:
                print(f"[{s['n']}] {s['title'][:70]} — {s['url']}")
            tok = (data.get("usage") or {}).get("tokens") or {}
            if tok.get("calls"):
                print(f"\n--- tokens: {tok['total_tokens']:,} in {tok['calls']} calls "
                      f"({tok['estimated_calls']} estimated) ---")
                for r in tok["by_model"]:
                    print(f"  {r['provider']}:{r['model']}  {r['calls']} calls  {r['input_tokens']:,} in  "
                          f"{r['output_tokens']:,} out  {r['cached_tokens']:,} cached")
            print("usage:", data["usage"], "| invalid citations removed:", data["invalid_citations"])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--mode", default="auto")
    ap.add_argument("--tz", default="Asia/Kolkata")
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()
    setup_observability()
    asyncio.run(main(a.question, a.mode, a.tz, a.raw))
    flush_traces()
