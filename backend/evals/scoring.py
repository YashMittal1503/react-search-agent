"""Scoring: deterministic assertions + global quality metrics + an optional LLM judge (rubrics, faithfulness)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .schema import Assertion, GoldItem

CACHE = Path(__file__).parent / "cache"

_REFUSAL = re.compile(r"\b(can't|cannot|won't|will not|unable to|not able to|i'm sorry|i am sorry|not appropriate|can not)\b.{0,80}"
                      r"\b(help|assist|provide|share|do that|with that|find|locate|give)", re.I | re.S)
_CLARIFY = re.compile(r"(\?\s*$|\?\s*\n|could you (clarify|specify|tell me)|which (one|city|location|place)|"
                      r"what (do you mean|are you referring)|please (specify|tell me|share)|assum(ing|e))", re.I | re.M)
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUM.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in (None, "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d"):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00")) if fmt is None else datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except Exception:  # noqa: BLE001
            continue
    return None


def tools_used(run: dict) -> set[str]:
    kinds = {s.get("kind") for s in run.get("steps", [])}
    mapping = {"search": "web_search", "news": "news_search", "fetch": "fetch_page", "weather": "get_weather"}
    return {mapping[k] for k in kinds if k in mapping}


def check(a: Assertion, run: dict) -> tuple[bool, str]:
    ans = run.get("answer", "") or ""
    low = ans.lower()
    cited = run.get("sources", [])
    if a.type == "contains_any":
        ok = any(v.lower() in low for v in a.values)
        return ok, "" if ok else f"none of {a.values}"
    if a.type == "contains_all":
        miss = [v for v in a.values if v.lower() not in low]
        return not miss, f"missing {miss}" if miss else ""
    if a.type == "not_contains":
        hit = [v for v in a.values if v.lower() in low]
        return not hit, f"contains {hit}" if hit else ""
    if a.type == "regex":
        ok = re.search(a.pattern or "", ans, re.I | re.S) is not None
        return ok, "" if ok else f"no match for /{a.pattern}/"
    if a.type == "numeric":
        target = float(a.value)  # type: ignore[arg-type]
        ok = any(abs(n - target) <= a.tolerance + 1e-9 for n in _numbers(ans))
        return ok, "" if ok else f"{target}±{a.tolerance} not found"
    if a.type == "must_call_tool":
        ok = str(a.value) in tools_used(run)
        return ok, "" if ok else f"{a.value} not used (used {sorted(tools_used(run))})"
    if a.type == "no_tool_calls":
        ok = not tools_used(run)
        return ok, "" if ok else f"used {sorted(tools_used(run))}"
    if a.type == "min_sources":
        ok = len(cited) >= int(a.value or 1)  # type: ignore[arg-type]
        return ok, "" if ok else f"{len(cited)} cited < {a.value}"
    if a.type == "must_cite_domain":
        ok = any(s.get("domain", "").endswith(str(a.value)) for s in cited)
        return ok, "" if ok else f"no cited source on {a.value}"
    if a.type == "freshness_days":
        now = datetime.now(UTC)
        ages = [(now - d).days for d in (_parse_date(s.get("published")) for s in cited) if d]
        ok = any(age <= float(a.value) for age in ages)  # type: ignore[arg-type]
        return ok, "" if ok else f"no cited source within {a.value} days (ages {sorted(ages)[:5]})"
    if a.type == "should_refuse":
        ok = bool(_REFUSAL.search(ans[:600]))
        return ok, "" if ok else "did not refuse"
    if a.type == "should_clarify":
        ok = bool(_CLARIFY.search(ans)) and len(run.get("sources", [])) <= 3
        return ok, "" if ok else "no clarifying question / stated assumption"
    return False, f"unknown assertion {a.type}"


def global_metrics(run: dict) -> dict[str, Any]:
    """Checks applied to every answer, whatever the item."""
    ans = run.get("answer", "") or ""
    cited = run.get("sources", [])
    seen = {s["url"] for s in run.get("all_sources", [])}
    markers = {int(n) for n in re.findall(r"\[(\d{1,3})\]", ans)}
    numbers = {s.get("n") for s in cited}
    valid = all(m in numbers for m in markers) and all(s["url"] in seen for s in cited)
    return {
        "citation_validity": 1.0 if valid else 0.0,                 # every [n] maps to a URL a tool returned
        "cited_count": len(cited),
        "invalid_citations_removed": len(run.get("invalid_citations", [])),
        "answered": bool(ans.strip()) and "couldn't finish writing" not in ans,
        "latency_s": run.get("usage", {}).get("seconds"),
        "searches": run.get("usage", {}).get("searches", 0),
        "fetches": run.get("usage", {}).get("fetches", 0),
        "route_intent": (run.get("route") or {}).get("intent"),
        "route_mode": (run.get("route") or {}).get("mode"),
    }


# ── LLM judge ────────────────────────────────────────────────────────────────
class RubricVerdict(BaseModel):
    criteria: list[bool] = Field(description="one boolean per criterion, in order: true if the answer satisfies it")
    notes: str = Field(default="", description="one short sentence on the main problem, if any")


class Faithfulness(BaseModel):
    supported: int = Field(description="number of checked claims fully supported by their cited source excerpt")
    total: int = Field(description="number of claims checked")
    unsupported_examples: list[str] = Field(default_factory=list)


def _cached(kind: str, payload: dict) -> tuple[Path, dict | None]:
    CACHE.mkdir(exist_ok=True)
    key = hashlib.sha256(json.dumps([kind, payload], sort_keys=True).encode()).hexdigest()[:32]
    path = CACHE / f"{kind}-{key}.json"
    return path, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else None)


async def judge_rubric(item: GoldItem, answer: str) -> dict | None:
    if not item.rubric:
        return None
    payload = {"q": item.query, "a": answer, "r": item.rubric}
    path, hit = _cached("rubric", payload)
    if hit:
        return hit
    from app.llm import chat_model

    criteria = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(item.rubric))
    prompt = (f"You grade answers from a web research assistant. Be strict but fair.\n\nQUESTION:\n{item.query}\n\n"
              f"ANSWER:\n{answer[:6000]}\n\nCRITERIA:\n{criteria}\n\nReturn one boolean per criterion.")
    llm = chat_model("judge", temperature=0).with_structured_output(RubricVerdict)
    v = await llm.ainvoke([("human", prompt)])
    v = v if isinstance(v, RubricVerdict) else RubricVerdict.model_validate(v)
    flags = (v.criteria + [False] * len(item.rubric))[: len(item.rubric)]
    out = {"score": sum(flags) / len(flags), "criteria": flags, "notes": v.notes}
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


async def judge_faithfulness(answer: str, excerpts: dict[int, str], max_claims: int = 6) -> dict | None:
    """Check cited sentences against the excerpt of the source they cite."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", answer) if re.search(r"\[\d+\]", s)]
    if not sentences or not excerpts:
        return None
    claims = []
    for s in sentences[:max_claims]:
        ns = [int(n) for n in re.findall(r"\[(\d+)\]", s)]
        ev = "\n".join(f"[{n}] {excerpts.get(n, '')[:1500]}" for n in ns if n in excerpts)
        if ev:
            claims.append({"claim": re.sub(r"\[\d+\]", "", s), "evidence": ev})
    if not claims:
        return None
    path, hit = _cached("faith", {"c": claims})
    if hit:
        return hit
    from app.llm import chat_model

    body = "\n\n".join(f"CLAIM {i + 1}: {c['claim']}\nEVIDENCE:\n{c['evidence']}" for i, c in enumerate(claims))
    prompt = ("For each claim, decide if the evidence fully supports it (numbers, names and dates must match). "
              f"Count supported claims.\n\n{body}")
    llm = chat_model("judge", temperature=0).with_structured_output(Faithfulness)
    v = await llm.ainvoke([("human", prompt)])
    v = v if isinstance(v, Faithfulness) else Faithfulness.model_validate(v)
    total = max(1, min(v.total or len(claims), len(claims)))
    out = {"score": min(1.0, v.supported / total), "checked": total, "unsupported": v.unsupported_examples[:3]}
    path.write_text(json.dumps(out), encoding="utf-8")
    return out
