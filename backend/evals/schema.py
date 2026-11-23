"""Golden dataset schema.

The golden set lives in ``evals/data/golden.jsonl``: one JSON object per line, ``//`` lines are comments.
Each line is validated into a :class:`GoldItem`. An item is either

* **single-turn**: it has a ``query`` (and item-level ``assertions`` / ``rubric``), or
* **multi-turn**: it has ``turns``, a list of :class:`Turn`. All turns run in the *same* conversation thread,
  so later turns can rely on earlier ones ("And tomorrow there?"). Each turn carries its own checks.

Internally both shapes are handled the same way: :meth:`GoldItem.all_turns` turns a single-turn item into a
one-element list, so the runner only ever iterates over turns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# The categories an item can belong to. Adding one here is all that is needed for the validator and the
# per-category table in reports to pick it up.
Category = Literal[
    "static_fact",        # timeless single facts (capital, author, constant)
    "historical_data",    # time-bounded series from the past (GDP 2010-2015): multi-value, numeric fidelity, data revisions
    "multi_hop",          # needs 2+ dependent lookups (director -> birthplace)
    "weather",            # live Open-Meteo data
    "news",               # fresh sources required
    "travel",             # itineraries, graded by rubric
    "comparison",         # structured X vs Y analysis
    "false_premise",      # the question assumes something untrue
    "unanswerable",       # the answer cannot be known (future, unrecorded)
    "ambiguous",          # must ask or state an assumption
    "conflicting",        # sources disagree; the answer must say so
    "math_date",          # arithmetic, unit and calendar reasoning
    "long_query",         # long, constraint-heavy or rambling prompts
    "harmful",            # must refuse
    "prompt_injection",   # instructions hidden in fetched pages must be ignored
    "robustness",         # blocked / JS-only / PDF / missing pages (see `focus`)
    "multi_turn",         # follow-ups, coreference, corrections, topic switches in one thread
    "chitchat",           # greetings and meta questions: no tools
]

Mode = Literal["quick", "deep"]


class Assertion(BaseModel):
    """One deterministic check on a single turn's output.

    contains_any:      answer contains at least one of `values` (case-insensitive)
    contains_all:      answer contains every value
    not_contains:      answer contains none of `values`
    regex:             answer matches `pattern` (case-insensitive)
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


class Turn(BaseModel):
    """One user message plus everything we expect of the reply to it."""

    query: str
    expected_mode: Mode | None = Field(default=None, description="route the router should pick for this turn")
    expected_intent: str | None = Field(default=None, description="router intent, e.g. weather / news / travel")
    mode: Literal["auto", "quick", "deep"] = Field(default="auto", description="mode forced by the 'user' (UI toggle)")
    assertions: list[Assertion] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list, description="criteria for the LLM judge")


class GoldItem(BaseModel):
    """A golden test case. See the module docstring for the single- vs multi-turn shapes."""

    id: str
    category: Category
    focus: str = Field(default="", description="the exact behaviour a robustness item tests, shown as 'robustness (focus)'")
    difficulty: Literal["easy", "medium", "hard"]
    split: Literal["dev", "holdout"] = "dev"
    smoke: bool = Field(default=False, description="part of the ~10-item quick suite")
    notes: str = ""

    # single-turn fields (ignored when `turns` is set)
    query: str = ""
    mode: Literal["auto", "quick", "deep"] = "auto"
    expected_intent: str | None = None
    expected_mode: Mode | None = None
    assertions: list[Assertion] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list, description="criteria for the LLM judge")

    # multi-turn
    turns: list[Turn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> GoldItem:
        """Enforce exactly one shape, and that every turn says which route it should take."""
        if bool(self.query) == bool(self.turns):
            raise ValueError("set exactly one of `query` (single-turn) or `turns` (multi-turn)")
        if self.turns and len(self.turns) < 2:
            raise ValueError("a multi-turn item needs at least 2 turns")
        if self.category == "multi_turn" and not self.turns:
            raise ValueError("category multi_turn requires `turns`")
        if any(t.expected_mode is None for t in self.all_turns()):
            raise ValueError("every item / turn must set expected_mode (quick | deep)")
        if self.category == "robustness" and not self.focus:
            raise ValueError("robustness items must set `focus`")
        return self

    def all_turns(self) -> list[Turn]:
        """The item as a list of turns (a single-turn item becomes one Turn)."""
        if self.turns:
            return self.turns
        return [Turn(query=self.query, expected_mode=self.expected_mode, expected_intent=self.expected_intent,
                     mode=self.mode, assertions=self.assertions, rubric=self.rubric)]

    @property
    def label(self) -> str:
        """Category as shown in reports, e.g. ``robustness (PDF extraction)``."""
        return f"{self.category} ({self.focus})" if self.focus else self.category


def load(path: Path, base_url: str | None = None) -> list[GoldItem]:
    """Parse and validate the golden JSONL file.

    Args:
        path: the ``.jsonl`` file.
        base_url: if given, every ``{FIXTURE}`` placeholder is replaced with it (the fixture site's URL).

    Raises:
        ValueError: on a malformed line (with its line number) or duplicate ids.
    """
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
