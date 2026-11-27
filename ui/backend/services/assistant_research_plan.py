"""Validate the research planner's response and the scope of its searches."""

import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)
from typing_extensions import Annotated

LibraryNextStep = Literal["ask", "rephrase", "focus"]

_SEARCH_TERMS_EXCLUDED = frozenset(
    "a an and the of in for by on what which how are does do that is were".split()
)
_SearchQuery = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class ResearchStream(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    query: _SearchQuery


class ContextSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: _SearchQuery
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ContextDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["decline", "clarify"]
    next_step: LibraryNextStep = "ask"


class FollowUpPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[_SearchQuery]
    reason: Annotated[str, StringConstraints(strip_whitespace=True)] = ""


class StreamFollowUpPlan(FollowUpPlan):
    @model_validator(mode="after")
    def explain_follow_up(self) -> Self:
        if self.queries and not self.reason:
            raise ValueError("A stream follow-up needs an evidence gap")
        return self


class DeepFocusPlan(FollowUpPlan):
    queries: list[_SearchQuery] = Field(min_length=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StreamPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    streams: list[ResearchStream] = Field(min_length=2, max_length=4)
    geographic_scope: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=300)
    ] = ""

    @model_validator(mode="after")
    def distinct_streams(self) -> Self:
        topics = {stream.topic.casefold() for stream in self.streams}
        searches: list[str] = []
        for stream in self.streams:
            if not is_new_query(stream.query, searches):
                raise ValueError("Each stream needs a distinct search")
            searches.append(stream.query)
        if len(topics) != len(self.streams):
            raise ValueError("Each stream needs a distinct topic")
        return self


CONTEXT_PLAN = TypeAdapter(ContextSearch | ContextDisposition)
INITIAL_PLAN: TypeAdapter[FollowUpPlan | StreamPlan] = TypeAdapter(
    FollowUpPlan | StreamPlan
)
DEEP_PLAN: TypeAdapter[DeepFocusPlan | StreamPlan] = TypeAdapter(
    DeepFocusPlan | StreamPlan
)
FOLLOW_UP: TypeAdapter[FollowUpPlan] = TypeAdapter(FollowUpPlan)
STREAM_FOLLOW_UP: TypeAdapter[FollowUpPlan] = TypeAdapter(StreamFollowUpPlan)


def _search_terms(query: str) -> set[str]:
    return set(re.findall(r"\w+", query.casefold())) - _SEARCH_TERMS_EXCLUDED


def is_new_query(candidate: str, previous: list[str]) -> bool:
    terms = _search_terms(candidate)
    if not terms:
        return False
    for query in previous:
        earlier = _search_terms(query)
        shared = len(terms & earlier)
        if shared / len(terms | earlier) >= 0.8:
            return False
        if shared >= 5 and shared / min(len(terms), len(earlier)) >= 0.83:
            return False
    return True


def verified_geographic_scope(scope: str, question: str, initial_query: str) -> str:
    """Carry forward only the scope named in the user's question or its resolved search."""
    requested = _search_terms(f"{question} {initial_query}")
    return scope if _search_terms(scope) <= requested else ""
