"""Golden dataset schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "static_fact", "multi_hop", "weather", "news", "travel", "comparison", "false_premise", "unanswerable",
    "ambiguous", "conflicting", "math_date", "non_english", "long_query", "harmful", "prompt_injection",
    "robustness", "chitchat",
]


class Assertion(BaseModel):
    """One deterministic check on a run.

    contains_any:      answer contains at least one of `values` (case-insensitive)
    contains_all:      answer contains every value
    not_contains:      answer contains none of `values`
    regex:             answer matches `pattern`
    numeric:           a number within `tolerance` of `value` appears in the answer
    must_call_tool:    the agent used tool `value` (web_search | news_search | fetch_page | get_weather)
    no_tool_calls:     the agent answered without tools
    min_sources:       at least `value` cited sources
    must_cite_domain:  a cited source is on `value` (suffix match)
    freshness_days:    at least one cited source was published within `value` days
    should_refuse:     the answer declines the request
    should_clarify:    the answer asks a clarifying question or states its assumption
    """

    type: Literal["contains_any", "contains_all", "not_contains", "regex", "numeric", "must_call_tool", "no_tool_calls",
                  "min_sources", "must_cite_domain", "freshness_days", "should_refuse", "should_clarify"]
    values: list[str] = Field(default_factory=list)
    pattern: str | None = None
    value: float | str | None = None
    tolerance: float = 0.0


class GoldItem(BaseModel):
    id: str
    query: str
    category: Category
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    split: Literal["dev", "holdout"] = "dev"
    smoke: bool = False
    mode: Literal["auto", "quick", "deep"] = "auto"
    expected_intent: str | None = None
    expected_mode: Literal["quick", "deep"] | None = None
    assertions: list[Assertion] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list, description="criteria for the LLM judge")
    notes: str = ""


def load(path: Path, base_url: str | None = None) -> list[GoldItem]:
    items = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if base_url:
            line = line.replace("{FIXTURE}", base_url)
        try:
            items.append(GoldItem.model_validate(json.loads(line)))
        except Exception as err:
            raise ValueError(f"{path.name}:{i}: {err}") from err
    ids = [x.id for x in items]
    dupes = {x for x in ids if ids.count(x) > 1}
    if dupes:
        raise ValueError(f"duplicate ids: {sorted(dupes)}")
    return items
