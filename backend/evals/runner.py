"""Run the golden set against the live agent and write a report.

    uv run python -m evals run --suite smoke            # ~11 items, ~6 min
    uv run python -m evals run --suite full --split dev
    uv run python -m evals run --ids fact-canberra,mt-pronoun-age --no-judge

Flow per item:
  1. every turn of the item is sent through ``run_turn`` in one conversation thread (single-turn items have one turn);
  2. each turn's assertions are checked and, unless ``--no-judge``, its rubric is graded by the LLM judge;
  3. the last turn that cited sources gets a claim-level faithfulness check (one judge call per item);
  4. turn results are rolled up into one item result, which passes only if every turn passes.

Reports go to ``evals/reports/<label>.md`` (+ ``.json``, git-ignored) and ``latest.md``.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent.runner import init_graph, run_turn
from app.observability import flush_traces, setup_observability
from app.settings import get_settings

from . import scoring
from .fixtures_site import serve_in_background
from .schema import GoldItem, Turn, load

DATA = Path(__file__).parent / "data" / "golden.jsonl"
REPORTS = Path(__file__).parent / "reports"
# Evals pretend to be a user in India; date-relative questions ("today") are interpreted in this zone.
TIMEZONE = "Asia/Kolkata"


async def _run_one_turn(turn: Turn, thread_id: str) -> tuple[dict[str, Any], list]:
    """Send one message through the agent and collect its streamed events.

    Returns:
        ``(run, contexts)``: ``run`` is the ``done`` payload plus ``steps`` (and ``error`` if it failed);
        ``contexts`` holds the RunContext, whose source registry has the excerpts the writer saw.
    """
    run: dict[str, Any] = {"steps": [], "answer": ""}
    steps: dict[int, dict] = {}   # step id -> merged step (streamed as "running", then updated to done/failed)
    contexts: list = []
    t0 = time.perf_counter()
    try:
        async for ev in run_turn(turn.query, thread_id, turn.mode, TIMEZONE, "en-US", capture=contexts):
            if ev["event"] == "step":
                steps.setdefault(ev["data"]["id"], {}).update(ev["data"])
            elif ev["event"] == "done":
                run.update(ev["data"])
            elif ev["event"] == "error":
                run["error"] = ev["data"]["message"]
    except Exception as err:  # noqa: BLE001 - an eval must record the failure, not crash the suite
        run["error"] = f"{type(err).__name__}: {err}"
    run["steps"] = list(steps.values())
    # Wall-clock latency as seen by the caller (includes streaming), overriding the agent's own estimate.
    run.setdefault("usage", {})["seconds"] = round(time.perf_counter() - t0, 1)
    return run, contexts


def _excerpts(run: dict, contexts: list) -> dict[int, str]:
    """Map each cited source number to the text the writer saw for it (full content, else the search snippet)."""
    if not contexts:
        return {}
    reg = contexts[0].registry
    out = {}
    for s in run.get("sources", []):
        src = reg.get(s["id"])
        out[s["n"]] = (src.content or src.snippet) if src else ""
    return out


async def run_item(item: GoldItem, judge: bool) -> dict[str, Any]:
    """Run every turn of ``item`` in one fresh thread and score it (see the module docstring for the flow)."""
    thread_id = f"eval-{item.id}-{uuid.uuid4().hex[:8]}"   # fresh thread: no memory shared between items or reruns
    history = ""                                           # "User: ... / Assistant: ..." transcript for the judge
    turns_out: list[dict[str, Any]] = []
    last_cited: tuple[dict, list] | None = None            # (run, contexts) of the last turn that cited sources

    for n, turn in enumerate(item.all_turns(), 1):
        run, contexts = await _run_one_turn(turn, thread_id)
        metrics = scoring.global_metrics(run)
        checks = []
        for a in turn.assertions:
            ok, why = scoring.check(a, run)
            checks.append({"type": a.type, "ok": ok, "why": why})
        t: dict[str, Any] = {
            "turn": n, "query": turn.query, "answer": run.get("answer", ""), "error": run.get("error"),
            "checks": checks, "assertion_pass": all(c["ok"] for c in checks) if checks else None,
            "metrics": metrics, "run_id": run.get("run_id"),
            "routing_ok": (turn.expected_intent is None or metrics["route_intent"] == turn.expected_intent)
            and (turn.expected_mode is None or metrics["route_mode"] == turn.expected_mode),
            "sources": [{"n": s.get("n"), "url": s.get("url")} for s in run.get("sources", [])],
        }
        if judge and run.get("answer") and turn.rubric:
            try:
                t["rubric"] = await scoring.judge_rubric(turn.query, turn.rubric, run["answer"], history)
            except Exception as err:  # noqa: BLE001 - judge quota errors shouldn't fail the item
                t["rubric_error"] = str(err)[:200]
        # A turn passes when its assertions pass, it produced an answer and (if judged) the rubric score is >= 0.6.
        t["passed"] = bool(t["assertion_pass"] in (True, None) and metrics["answered"]
                           and (t.get("rubric") is None or t["rubric"]["score"] >= 0.6))
        turns_out.append(t)
        if run.get("sources"):
            last_cited = (run, contexts)
        history += f"User: {turn.query}\nAssistant: {(run.get('answer') or '')[:800]}\n"

    return await _roll_up(item, turns_out, last_cited if judge else None)


async def _roll_up(item: GoldItem, turns: list[dict], last_cited: tuple[dict, list] | None) -> dict[str, Any]:
    """Combine per-turn results into one item result.

    Single-turn items look exactly like before (no ``turns`` key). Multi-turn items keep the per-turn detail
    under ``turns`` and prefix failure reasons with the turn number (``t2: ...``).
    """
    multi = len(turns) > 1
    checks = [{**c, "why": (f"t{t['turn']}: " if multi and c["why"] else "") + c["why"]} for t in turns for c in t["checks"]]
    ms = [t["metrics"] for t in turns]
    metrics = {
        "citation_validity": min(m["citation_validity"] for m in ms),     # one bad turn makes the item invalid
        "cited_count": sum(m["cited_count"] for m in ms),
        "invalid_citations_removed": sum(m["invalid_citations_removed"] for m in ms),
        "answered": all(m["answered"] for m in ms),
        "latency_s": round(sum(m["latency_s"] or 0 for m in ms), 1),     # total time for the whole conversation
        "searches": sum(m["searches"] for m in ms),
        "fetches": sum(m["fetches"] for m in ms),
        "route_intent": [m["route_intent"] for m in ms] if multi else ms[0]["route_intent"],
        "route_mode": [m["route_mode"] for m in ms] if multi else ms[0]["route_mode"],
    }
    result: dict[str, Any] = {
        "id": item.id, "category": item.category, "label": item.label, "difficulty": item.difficulty,
        "split": item.split, "turns_count": len(turns), "query": " -> ".join(t["query"] for t in turns),
        "answer": turns[-1]["answer"], "error": next((t["error"] for t in turns if t["error"]), None),
        "checks": checks, "assertion_pass": all(c["ok"] for c in checks) if checks else None,
        "metrics": metrics, "run_id": turns[-1]["run_id"],
        "routing_ok": all(t["routing_ok"] for t in turns), "turn_routing": [t["routing_ok"] for t in turns],
        "sources": turns[-1]["sources"], "passed": all(t["passed"] for t in turns),
    }
    judged = [t["rubric"] for t in turns if t.get("rubric")]
    if judged:
        result["rubric"] = {"score": round(statistics.mean(j["score"] for j in judged), 3),
                            "notes": "; ".join(j["notes"] for j in judged if j.get("notes"))}
    if multi:
        result["turns"] = turns
    if last_cited:
        run, contexts = last_cited
        try:
            result["faithfulness"] = await scoring.judge_faithfulness(run["answer"], _excerpts(run, contexts))
        except Exception as err:  # noqa: BLE001
            result["faithfulness_error"] = str(err)[:200]
    return result


def summarize(results: list[dict]) -> dict[str, Any]:
    """Aggregate item results into suite metrics. Means skip items where a metric doesn't apply (``None``)."""

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.mean(xs), 3) if xs else None

    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    lat = sorted(r["metrics"]["latency_s"] or 0 for r in results)
    turn_routing = [ok for r in results for ok in r.get("turn_routing", [r["routing_ok"]])]
    return {
        "items": len(results),
        "turns": sum(r.get("turns_count", 1) for r in results),
        "pass_rate": mean([1.0 if r["passed"] else 0.0 for r in results]),
        "assertion_pass_rate": mean([1.0 if r["assertion_pass"] else 0.0 for r in results if r["assertion_pass"] is not None]),
        "citation_validity": mean([r["metrics"]["citation_validity"] for r in results]),
        "faithfulness": mean([(r.get("faithfulness") or {}).get("score") for r in results]),
        "rubric_score": mean([(r.get("rubric") or {}).get("score") for r in results]),
        "routing_accuracy": mean([1.0 if ok else 0.0 for ok in turn_routing]),   # per turn, not per item
        "answered_rate": mean([1.0 if r["metrics"]["answered"] else 0.0 for r in results]),
        "latency_p50_s": lat[len(lat) // 2] if lat else None,
        "latency_p95_s": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
        "avg_searches": mean([r["metrics"]["searches"] for r in results]),
        "avg_fetches": mean([r["metrics"]["fetches"] for r in results]),
        "by_category": {c: {"n": len(rs), "pass_rate": mean([1.0 if r["passed"] else 0.0 for r in rs])}
                        for c, rs in sorted(by_cat.items())},
    }


def to_markdown(summary: dict, results: list[dict], label: str) -> str:
    """Render the human-readable report: headline metrics, per-category table, then each failure with its reason."""
    s = summary
    lines = [f"# Eval report: {label}", "",
             f"Items: **{s['items']}** ({s['turns']} turns) · pass rate **{s['pass_rate']}** · "
             f"citation validity **{s['citation_validity']}** · faithfulness **{s['faithfulness']}** · "
             f"rubric **{s['rubric_score']}** · routing **{s['routing_accuracy']}**", "",
             f"Latency p50 {s['latency_p50_s']}s · p95 {s['latency_p95_s']}s · avg searches {s['avg_searches']} · "
             f"avg pages read {s['avg_fetches']}", "",
             "| Category | n | pass rate |", "|---|---|---|"]
    for c, v in s["by_category"].items():
        lines.append(f"| {c} | {v['n']} | {v['pass_rate']} |")
    lines += ["", "## Failures", ""]
    for r in results:
        if not r["passed"]:
            why = ("; ".join(c["why"] for c in r["checks"] if not c["ok"]) or (r.get("rubric") or {}).get("notes")
                   or r.get("error") or "rubric below 0.6")
            lines.append(f"- **{r['id']}** ({r.get('label', r['category'])}): {why}")
    return "\n".join(lines) + "\n"


async def run_suite(suite: str, split: str | None, ids: list[str] | None, judge: bool, langsmith: bool) -> Path:
    """Select items, run them one by one (free-tier quotas don't allow parallelism) and write the reports."""
    base = serve_in_background(public=True)
    get_settings().allow_private_fetch = True      # the fixture site lives on 127.0.0.1
    await init_graph(memory=True)                  # in-memory checkpointer: multi-turn items need thread memory
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
        if langsmith:
            for t in r.get("turns", [r]):          # one LangSmith trace per turn
                if t.get("run_id"):
                    _langsmith_feedback(t, r)
    summary = summarize(results)
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    label = f"{'ids' if ids else suite}{'-' + split if split else ''}-{stamp}"
    (REPORTS / f"{label}.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    md = REPORTS / f"{label}.md"
    md.write_text(to_markdown(summary, results, label), encoding="utf-8")
    (REPORTS / "latest.md").write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "by_category"}, indent=2))
    return md


def _langsmith_feedback(turn: dict, item: dict) -> None:
    """Attach scores to one turn's LangSmith trace (needs LANGSMITH_API_KEY; tracing turns on automatically).

    Args:
        turn: a per-turn result, or the item result itself for single-turn items.
        item: the item result, which carries the item-level faithfulness score.
    """
    try:
        from langsmith import Client

        c = Client()
        c.create_feedback(turn["run_id"], key="passed", score=1.0 if turn["passed"] else 0.0)
        c.create_feedback(turn["run_id"], key="citation_validity", score=turn["metrics"]["citation_validity"])
        if turn.get("rubric"):
            c.create_feedback(turn["run_id"], key="rubric", score=turn["rubric"]["score"], comment=turn["rubric"].get("notes"))
        if item.get("faithfulness") and turn["run_id"] == item["run_id"]:
            c.create_feedback(turn["run_id"], key="faithfulness", score=item["faithfulness"]["score"])
    except Exception as err:  # noqa: BLE001
        print("    (langsmith feedback skipped:", str(err)[:100], ")")


def main_run(args) -> None:
    """Entry point for ``python -m evals run`` (flags are defined in ``evals/__main__.py``)."""
    ids = [x.strip() for x in args.ids.split(",")] if args.ids else None
    setup_observability()
    path = asyncio.run(run_suite(args.suite, args.split, ids, not args.no_judge, args.langsmith))
    flush_traces()   # LangSmith uploads in a background thread; wait before the process exits
    print("report:", path)
