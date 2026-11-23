"""Run the golden set against the live agent and write a report.

    uv run python -m evals run --suite smoke            # 9 items, ~5 min
    uv run python -m evals run --suite full --split dev
    uv run python -m evals run --ids fact-canberra,inj-garden --no-judge
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent.runner import run_turn
from app.settings import get_settings

from . import scoring
from .fixtures_site import serve_in_background
from .schema import GoldItem, load

DATA = Path(__file__).parent / "data" / "golden.jsonl"
REPORTS = Path(__file__).parent / "reports"


async def run_item(item: GoldItem, judge: bool) -> dict[str, Any]:
    run: dict[str, Any] = {"steps": [], "answer": ""}
    steps: dict[int, dict] = {}
    contexts: list = []
    t0 = time.perf_counter()
    try:
        async for ev in run_turn(item.query, None, item.mode, "Asia/Kolkata", "en-US", capture=contexts):
            if ev["event"] == "step":
                steps.setdefault(ev["data"]["id"], {}).update(ev["data"])
            elif ev["event"] == "done":
                run.update(ev["data"])
            elif ev["event"] == "error":
                run["error"] = ev["data"]["message"]
    except Exception as err:  # noqa: BLE001
        run["error"] = f"{type(err).__name__}: {err}"
    run["steps"] = list(steps.values())
    run.setdefault("usage", {})["seconds"] = round(time.perf_counter() - t0, 1)

    checks = []
    for a in item.assertions:
        ok, why = scoring.check(a, run)
        checks.append({"type": a.type, "ok": ok, "why": why})
    metrics = scoring.global_metrics(run)
    result: dict[str, Any] = {
        "id": item.id, "category": item.category, "difficulty": item.difficulty, "split": item.split,
        "query": item.query, "answer": run.get("answer", ""), "error": run.get("error"),
        "checks": checks, "assertion_pass": all(c["ok"] for c in checks) if checks else None,
        "metrics": metrics, "run_id": run.get("run_id"),
        "routing_ok": (item.expected_intent is None or metrics["route_intent"] == item.expected_intent)
        and (item.expected_mode is None or metrics["route_mode"] == item.expected_mode),
        "sources": [{"n": s.get("n"), "url": s.get("url")} for s in run.get("sources", [])],
    }
    if judge and run.get("answer"):
        try:
            result["rubric"] = await scoring.judge_rubric(item, run["answer"])
        except Exception as err:  # noqa: BLE001
            result["rubric_error"] = str(err)[:200]
        if contexts and run.get("sources"):
            reg = contexts[0].registry
            excerpts = {s["n"]: ((reg.get(s["id"]).content or reg.get(s["id"]).snippet) if reg.get(s["id"]) else "") for s in run["sources"]}
            try:
                result["faithfulness"] = await scoring.judge_faithfulness(run["answer"], excerpts)
            except Exception as err:  # noqa: BLE001
                result["faithfulness_error"] = str(err)[:200]
    result["passed"] = bool(result["assertion_pass"] in (True, None) and metrics["answered"]
                            and (result.get("rubric") is None or result["rubric"]["score"] >= 0.6))
    return result


def summarize(results: list[dict]) -> dict[str, Any]:
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.mean(xs), 3) if xs else None

    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    lat = sorted(r["metrics"]["latency_s"] or 0 for r in results)
    return {
        "items": len(results),
        "pass_rate": mean([1.0 if r["passed"] else 0.0 for r in results]),
        "assertion_pass_rate": mean([1.0 if r["assertion_pass"] else 0.0 for r in results if r["assertion_pass"] is not None]),
        "citation_validity": mean([r["metrics"]["citation_validity"] for r in results]),
        "faithfulness": mean([(r.get("faithfulness") or {}).get("score") for r in results]),
        "rubric_score": mean([(r.get("rubric") or {}).get("score") for r in results]),
        "routing_accuracy": mean([1.0 if r["routing_ok"] else 0.0 for r in results]),
        "answered_rate": mean([1.0 if r["metrics"]["answered"] else 0.0 for r in results]),
        "latency_p50_s": lat[len(lat) // 2] if lat else None,
        "latency_p95_s": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
        "avg_searches": mean([r["metrics"]["searches"] for r in results]),
        "avg_fetches": mean([r["metrics"]["fetches"] for r in results]),
        "by_category": {c: {"n": len(rs), "pass_rate": mean([1.0 if r["passed"] else 0.0 for r in rs])} for c, rs in sorted(by_cat.items())},
    }


def to_markdown(summary: dict, results: list[dict], label: str) -> str:
    s = summary
    lines = [f"# Eval report: {label}", "",
             f"Items: **{s['items']}** · pass rate **{s['pass_rate']}** · citation validity **{s['citation_validity']}** · "
             f"faithfulness **{s['faithfulness']}** · rubric **{s['rubric_score']}** · routing **{s['routing_accuracy']}**", "",
             f"Latency p50 {s['latency_p50_s']}s · p95 {s['latency_p95_s']}s · avg searches {s['avg_searches']} · avg pages read {s['avg_fetches']}", "",
             "| Category | n | pass rate |", "|---|---|---|"]
    for c, v in s["by_category"].items():
        lines.append(f"| {c} | {v['n']} | {v['pass_rate']} |")
    lines += ["", "## Failures", ""]
    for r in results:
        if not r["passed"]:
            why = "; ".join(c["why"] for c in r["checks"] if not c["ok"]) or (r.get("rubric") or {}).get("notes") or r.get("error") or "rubric below 0.6"
            lines.append(f"- **{r['id']}** ({r['category']}): {why}")
    return "\n".join(lines) + "\n"


async def run_suite(suite: str, split: str | None, ids: list[str] | None, judge: bool, langsmith: bool) -> Path:
    base = serve_in_background(public=True)
    get_settings().allow_private_fetch = True      # the fixture site lives on 127.0.0.1
    items = load(DATA, base)
    if ids:
        items = [i for i in items if i.id in ids]
    elif suite == "smoke":
        items = [i for i in items if i.smoke]
    if split:
        items = [i for i in items if i.split == split]
    results = []
    for n, item in enumerate(items, 1):
        print(f"[{n}/{len(items)}] {item.id} …", flush=True)
        r = await run_item(item, judge)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"    {status} in {r['metrics']['latency_s']}s · cited {r['metrics']['cited_count']} · "
              + ("; ".join(c["why"] for c in r["checks"] if not c["ok"]) or ""), flush=True)
        results.append(r)
        if langsmith and r.get("run_id"):
            _langsmith_feedback(r)
    summary = summarize(results)
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    label = f"{'ids' if ids else suite}{'-' + split if split else ''}-{stamp}"
    (REPORTS / f"{label}.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    md = REPORTS / f"{label}.md"
    md.write_text(to_markdown(summary, results, label), encoding="utf-8")
    (REPORTS / "latest.md").write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "by_category"}, indent=2))
    return md


def _langsmith_feedback(r: dict) -> None:
    """Attach scores to the agent's LangSmith trace (needs LANGSMITH_API_KEY + tracing on)."""
    try:
        from langsmith import Client

        c = Client()
        c.create_feedback(r["run_id"], key="passed", score=1.0 if r["passed"] else 0.0)
        c.create_feedback(r["run_id"], key="citation_validity", score=r["metrics"]["citation_validity"])
        if r.get("rubric"):
            c.create_feedback(r["run_id"], key="rubric", score=r["rubric"]["score"], comment=r["rubric"].get("notes"))
        if r.get("faithfulness"):
            c.create_feedback(r["run_id"], key="faithfulness", score=r["faithfulness"]["score"])
    except Exception as err:  # noqa: BLE001
        print("    (langsmith feedback skipped:", str(err)[:100], ")")


def main_run(args) -> None:
    ids = [x.strip() for x in args.ids.split(",")] if args.ids else None
    path = asyncio.run(run_suite(args.suite, args.split, ids, not args.no_judge, args.langsmith))
    print("report:", path)
