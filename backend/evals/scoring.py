"""Scoring for one agent turn.

Three layers, cheapest first:

1. :func:`check` runs the item's deterministic :class:`~evals.schema.Assertion` s (substring, regex, numeric,
   tool use, sources, freshness, refusal/clarification) against the turn's ``done`` payload.
2. :func:`global_metrics` computes item-independent numbers for every turn (citation validity, latency,
   searches, route) so the summary can average them.
3. The LLM judge (:func:`judge_rubric`, :func:`judge_faithfulness`) grades free-form quality and whether cited
   sentences are supported by the excerpt the writer actually saw. Verdicts are cached on disk by a hash of
   their inputs, so re-running an unchanged answer costs no quota.

``run`` everywhere is the dict built by ``evals.runner``: the ``done`` event's data plus ``steps``.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .schema import Assertion

# Judge verdicts, keyed by a hash of (kind, inputs). Delete the folder to force re-judging.
CACHE = Path(__file__).parent / "cache"

# A refusal = an apology/negation followed shortly by a "help/provide/..." verb, within the first 600 chars.
_REFUSAL = re.compile(r"\b(can't|cannot|won't|will not|unable to|not able to|i'm sorry|i am sorry|not appropriate|can not)\b.{0,80}"
                      r"\b(help|assist|provide|share|do that|with that|find|locate|give)", re.I | re.S)
# A clarification = ends on a question, asks which one, or explicitly states an assumption.
_CLARIFY = re.compile(r"(\?\s*$|\?\s*\n|could you (clarify|specify|tell me)|which (one|city|location|place)|"
                      r"what (do you mean|are you referring)|please (specify|tell me|share)|assum(ing|e))", re.I | re.M)
# Any number, allowing thousands separators and decimals ("19,671.51").
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _numbers(text: str) -> list[float]:
    """Every number in ``text`` as a float (thousands separators removed)."""
    out = []
    for m in _NUM.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _parse_date(s: str | None) -> datetime | None:
    """Parse a source's ``published`` field (ISO, RFC-822 from RSS, or plain date) into an aware datetime."""
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
    """Tool names the agent used, derived from the timeline steps it streamed (step kind -> tool name)."""
    kinds = {s.get("kind") for s in run.get("steps", [])}
    mapping = {"search": "web_search", "news": "news_search", "fetch": "fetch_page", "weather": "get_weather"}
    return {mapping[k] for k in kinds if k in mapping}


def check(a: Assertion, run: dict) -> tuple[bool, str]:
    """Evaluate one assertion. Returns ``(passed, reason)``; ``reason`` is empty when it passed."""
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
        # Asking for clarification while also doing lots of research counts as not clarifying.
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
        # Agent tokens for this turn (judge tokens are tracked separately by the runner).
        "total_tokens": ((run.get("usage") or {}).get("tokens") or {}).get("total_tokens", 0),
        "route_intent": (run.get("route") or {}).get("intent"),
        "route_mode": (run.get("route") or {}).get("mode"),
    }


# ── LLM judge ────────────────────────────────────────────────────────────────
class RubricVerdict(BaseModel):
    """Structured output the judge must return for a rubric."""

    criteria: list[bool] = Field(description="one boolean per criterion, in order: true if the answer satisfies it")
    notes: str = Field(default="", description="one short sentence on the main problem, if any")


class Faithfulness(BaseModel):
    """Structured output the judge must return for the claim-support check."""

    supported: int = Field(description="number of checked claims fully supported by their cited source excerpt")
    total: int = Field(description="number of claims checked")
    unsupported_examples: list[str] = Field(default_factory=list)


def _cached(kind: str, payload: dict) -> tuple[Path, dict | None]:
    """Return the cache path for this judgement and the cached verdict, if any."""
    CACHE.mkdir(exist_ok=True)
    key = hashlib.sha256(json.dumps([kind, payload], sort_keys=True).encode()).hexdigest()[:32]
    path = CACHE / f"{kind}-{key}.json"
    return path, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else None)


async def judge_rubric(query: str, rubric: list[str], answer: str, history: str = "", callbacks: list | None = None) -> dict | None:
    """Grade ``answer`` against each rubric criterion with the judge tier.

    Args:
        query: the user message this answer replies to.
        rubric: criteria, each judged true/false independently.
        answer: the agent's final answer (markdown).
        history: for later turns of a multi-turn item, the earlier conversation, so criteria like
            "resolves 'he' to Christopher Nolan" can be judged.
        callbacks: LangChain callbacks for the judge call (the runner passes a TokenTracker). Cache hits make no
            call and so use no tokens.

    Returns:
        ``{"score": fraction of criteria met, "criteria": [bool...], "notes": str}`` or ``None`` without a rubric.
    """
    if not rubric:
        return None
    payload = {"q": query, "a": answer, "r": rubric}
    if history:                       # only added when present, so single-turn cache keys stay unchanged
        payload["h"] = history
    path, hit = _cached("rubric", payload)
    if hit:
        return hit
    from app.llm import chat_model  # imported lazily: offline tests import this module without keys

    criteria = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(rubric))
    convo = f"EARLIER CONVERSATION:\n{history[:3000]}\n\n" if history else ""
    prompt = (f"You grade answers from a web research assistant. Be strict but fair.\n\n{convo}QUESTION:\n{query}\n\n"
              f"ANSWER:\n{answer[:6000]}\n\nCRITERIA:\n{criteria}\n\nReturn one boolean per criterion.")
    llm = chat_model("judge", temperature=0).with_structured_output(RubricVerdict)
    v = await llm.ainvoke([("human", prompt)], config={"callbacks": callbacks or [], "metadata": {"usage_step": "judge_rubric"}})
    v = v if isinstance(v, RubricVerdict) else RubricVerdict.model_validate(v)
    # Pad/trim so a judge that returns the wrong number of booleans can't crash or inflate the score.
    flags = (v.criteria + [False] * len(rubric))[: len(rubric)]
    out = {"score": sum(flags) / len(flags), "criteria": flags, "notes": v.notes}
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


async def judge_faithfulness(answer: str, excerpts: dict[int, str], max_claims: int = 6,
                             callbacks: list | None = None) -> dict | None:
    """Check cited sentences against the excerpt of the source they cite.

    Only sentences containing ``[n]`` markers are claims. Up to ``max_claims`` of them are sent to the judge,
    each with the excerpts (``excerpts[n]``, the text the writer saw for source n) it cites.

    Returns:
        ``{"score": supported/checked, "checked": int, "unsupported": [examples]}`` or ``None`` if nothing is cited.
    """
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
    v = await llm.ainvoke([("human", prompt)], config={"callbacks": callbacks or [], "metadata": {"usage_step": "judge_faithfulness"}})
    v = v if isinstance(v, Faithfulness) else Faithfulness.model_validate(v)
    total = max(1, min(v.total or len(claims), len(claims)))
    out = {"score": min(1.0, v.supported / total), "checked": total, "unsupported": v.unsupported_examples[:3]}
    path.write_text(json.dumps(out), encoding="utf-8")
    return out
