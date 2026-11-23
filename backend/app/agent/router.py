"""Query router: intent, mode (quick/deep), scene and a standalone search query.
LLM structured output on the fast tier with a keyword heuristic as an instant fallback."""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from ..llm import chat_model
from .prompts import ROUTER

logger = logging.getLogger(__name__)

Intent = Literal["weather", "news", "travel", "finance", "sports", "tech", "science", "health", "food", "shopping", "general", "chitchat"]


class Route(BaseModel):
    intent: Intent = Field(description="Topic of the message")
    mode: Literal["quick", "deep"] = Field(description="quick = 1-3 lookups, deep = multi-step research")
    location: str | None = Field(default=None, description="Place the question is about, if any")
    recency_days: int | None = Field(default=None, description="1 today, 7 week, 30 month, null timeless")
    search_query: str = Field(description="Standalone search query")
    travel_setting: Literal["beach", "mountain", "city", "desert", "snow", "countryside"] | None = None


SCENES = {
    "weather": "weather", "news": "news", "travel": "travel", "finance": "finance", "sports": "sports",
    "tech": "tech", "science": "space", "health": "health", "food": "food", "shopping": "default",
    "general": "default", "chitchat": "default",
}

_KEYWORDS: list[tuple[str, str]] = [
    ("weather", r"\b(weather|forecast|temperature|rain|raining|rainy|snow|snowing|humidity|umbrella|sunny|windy|degrees)\b"),
    ("travel", r"\b(itinerary|trip|travel|vacation|holiday|visit|things to do|places to see|hotel|flight|tour|backpack)\b"),
    ("news", r"\b(news|latest|headlines|breaking|today's|this week|trending|trends|announced|update on)\b"),
    ("finance", r"\b(stock|share price|market|nasdaq|sensex|nifty|crypto|bitcoin|inflation|interest rate|earnings|ipo|gdp|price of)\b"),
    ("sports", r"\b(match|score|football|soccer|cricket|nba|nfl|ipl|world cup|tennis|f1|formula 1|olympics|league)\b"),
    ("tech", r"\b(ai|llm|gpu|iphone|android|software|programming|python|javascript|startup|chip|openai|nvidia|app)\b"),
    ("science", r"\b(space|nasa|planet|galaxy|physics|quantum|biology|chemistry|research paper|telescope|mars|moon)\b"),
    ("health", r"\b(health|symptom|disease|diet|exercise|vaccine|medicine|sleep|calories|protein)\b"),
    ("food", r"\b(recipe|restaurant|cook|food|dish|cuisine|cafe|eat|dinner|breakfast|lunch)\b"),
]
_DEEP = re.compile(r"\b(itinerary|plan|compare|comparison|vs\.?|versus|pros and cons|research|in[- ]depth|detailed|report|analy[sz]e|"
                   r"step[- ]by[- ]step|best .* for|day trip|\d+[- ]day)\b", re.I)
_CHITCHAT = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|cool|who are you|what can you do|good (morning|evening))\b[\s!.?]*$", re.I)
_RECENT = re.compile(r"\b(today|now|current(ly)?|latest|live|tonight|right now|breaking)\b", re.I)
_WEEK = re.compile(r"\b(this week|recent(ly)?|past few days|trending)\b", re.I)


def heuristic_route(question: str) -> Route:
    q = question.lower()
    intent = "general"
    if _CHITCHAT.match(q):
        intent = "chitchat"
    else:
        for name, rx in _KEYWORDS:
            if re.search(rx, q):
                intent = name
                break
    mode = "deep" if (_DEEP.search(q) or len(q.split()) > 28) and intent != "chitchat" else "quick"
    recency = 1 if _RECENT.search(q) else 7 if _WEEK.search(q) else (3 if intent == "news" else None)
    m = re.search(r"\b(?:in|at|for|to)\s+([A-Z][\w\-]+(?:[ ,]+[A-Z][\w\-]+){0,2})", question)
    return Route(intent=intent, mode=mode, location=m.group(1).strip(" ,") if m else None, recency_days=recency, search_query=question)


async def route_question(question: str, history: str, today: str, tz: str, config=None) -> Route:
    fallback = heuristic_route(question)
    if fallback.intent == "chitchat":
        return fallback
    try:
        llm = chat_model("fast", temperature=0).with_structured_output(Route)
        route = await llm.ainvoke(
            [("system", ROUTER.format(today=today, tz=tz, history=history or "(none)")), ("human", question)],
            config=config,
        )
        if not isinstance(route, Route):
            route = Route.model_validate(route)
        if not route.search_query.strip():
            route.search_query = question
        return route
    except Exception as err:  # noqa: BLE001
        logger.warning("router LLM failed, using heuristic: %s", str(err)[:200])
        return fallback


def scene_for(route: Route) -> dict:
    params: dict = {}
    if route.intent == "travel" and route.travel_setting:
        params["setting"] = route.travel_setting
    if route.location:
        params["location"] = route.location
    return {"scene": SCENES.get(route.intent, "default"), "params": params}
