"""The shared LangGraph workflow for Assistant and Deep Research."""

import asyncio
import logging
import operator
import re
from collections import Counter
from dataclasses import dataclass
from textwrap import shorten
from typing import Any, Literal, Self, TypedDict, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from starlette.concurrency import run_in_threadpool
from typing_extensions import Annotated

from ui.backend.services.agent_passages import passage_for_agent
from utils.llm_factory import message_text

logger = logging.getLogger(__name__)

Passage = dict[str, Any]
_CITATION = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")
_SEARCH_TERMS_EXCLUDED = frozenset(
    "a an and the of in for by on what which how are does do that is were".split()
)
_JSON_FENCE = re.compile(r"`{3}(?:json)?\s*(\{.*?\})\s*`{3}", re.DOTALL | re.IGNORECASE)
_NO_EVIDENCE = (
    "I couldn’t find evidence in the selected collection to answer this question."
)


@dataclass(frozen=True)
class ResearchLimits:
    """Bound the number of searches and the evidence handed to the writer."""

    searches: int
    initial_passages: int = 12
    follow_up_passages: int = 6
    previous_passages: int = 6
    searches_per_stream: int = 2


class ResearchStream(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class FollowUpPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
        ]
    ] = Field(max_length=3)
    reason: Annotated[str, StringConstraints(strip_whitespace=True)] = ""


class StreamFollowUpPlan(FollowUpPlan):
    @model_validator(mode="after")
    def explain_follow_up(self) -> Self:
        if self.queries and not self.reason:
            raise ValueError("A stream follow-up needs an evidence gap")
        return self


class StreamPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    streams: list[ResearchStream] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def distinct_streams(self) -> Self:
        topics = {stream.topic.casefold() for stream in self.streams}
        searches: list[str] = []
        for stream in self.streams:
            if not _is_new_query(stream.query, searches):
                raise ValueError("Each stream needs a distinct search")
            searches.append(stream.query)
        if len(topics) != len(self.streams):
            raise ValueError("Each stream needs a distinct topic")
        return self


class StreamTask(TypedDict):
    order: int
    topic: str
    question: str
    history: list[BaseMessage]
    evidence: list[Passage]
    searches: list[str]
    next_query: str
    reason: str
    budget: int


class StreamResult(TypedDict):
    order: int
    topic: str
    evidence: list[Passage]


class ResearchState(TypedDict, total=False):
    query: str
    messages: list[BaseMessage]
    evidence: list[Passage]
    tasks: list[StreamTask]
    findings: Annotated[list[StreamResult], operator.add]
    answer: str


_Plan = TypeVar("_Plan")
_INITIAL_PLAN: TypeAdapter[FollowUpPlan | StreamPlan] = TypeAdapter(
    FollowUpPlan | StreamPlan
)
_FOLLOW_UP: TypeAdapter[FollowUpPlan] = TypeAdapter(FollowUpPlan)
_STREAM_FOLLOW_UP: TypeAdapter[FollowUpPlan] = TypeAdapter(StreamFollowUpPlan)
_QUERY_FORMAT = (
    'Return only JSON like {"queries":["a focused search"],'
    '"reason":"The prior passages did not report recovery rates."} '
    'or {"queries":[]} when no more searches are needed.'
)
_STREAM_FORMAT = (
    'For distinct parts return JSON like {"streams":[{"topic":"Coverage",'
    '"query":"treatment reach and barriers"},{"topic":"Costs",'
    '"query":"cost per beneficiary and cost per cure"}]}. ' + _QUERY_FORMAT
)


def _search_terms(query: str) -> set[str]:
    return set(re.findall(r"\w+", query.casefold())) - _SEARCH_TERMS_EXCLUDED


def _is_new_query(candidate: str, previous: list[str]) -> bool:
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


def _admit_passages(
    results: list[Passage], existing: list[Passage], limit: int
) -> list[Passage]:
    """Prefer distinct reports, and retain each admitted passage across rounds."""
    seen = {p["global_index"] for p in existing}
    preferred: list[Passage] = []
    deferred: list[Passage] = []
    per_report: Counter[str] = Counter()
    for passage in results:
        index = passage["global_index"]
        if index in seen or not (passage["text"] or "").strip():
            continue
        seen.add(index)
        report = passage["doc_id"] or passage["title"]
        (preferred if per_report[report] < 2 else deferred).append(passage)
        per_report[report] += 1
    return (preferred + deferred)[:limit]


def _prior_passages(
    sources: list[Passage], messages: list[BaseMessage], limit: int
) -> list[Passage]:
    """Bring forward sources cited in recent assistant messages."""
    cited = {
        int(number)
        for msg in messages
        if isinstance(msg, AIMessage)
        for group in _CITATION.findall(message_text(msg))
        for number in re.findall(r"\d+", group)
    }
    return [
        {
            "global_index": s["index"],
            "doc_id": s.get("docId"),
            "title": s["title"],
            "page": s.get("page"),
            "text": s["text"],
        }
        for s in sources
        if s.get("index") in cited and s.get("text")
    ][-limit:]


def _render_evidence(passages: list[Passage]) -> str:
    rows = []
    for p in passages:
        content = passage_for_agent(p["text"])
        if len(content) > 2400:
            content = content[:1800] + "\n[excerpt continues]\n" + content[-600:]
        rows.append(f'[{p["global_index"]}] {p["title"]}\n{content}')
    return "\n\n".join(rows)


def _invalid_citations(answer: str, evidence: list[Passage]) -> list[str]:
    allowed = {p["global_index"] for p in evidence}
    return [
        group
        for group in _CITATION.findall(answer)
        if "-" in group
        or "–" in group
        or any(int(n) not in allowed for n in group.split(","))
    ]


class ResearchWorkflow:
    """Run retrieval, plan another search when useful, and write from the evidence."""

    def __init__(
        self,
        llm,
        tracker,
        planner: str,
        writer: str,
        limits: ResearchLimits,
        opening: str,
    ):
        if limits.searches < 1 or limits.searches_per_stream < 1:
            raise ValueError("Assistant search budgets must be at least one")
        self.llm = llm
        self.tracker = tracker
        self.planner = planner
        self.opening = opening
        self.writer = writer
        self.limits = limits
        # Research streams can plan concurrently. Keep citation allocation and
        # progress in search order since the tracker is shared for the whole turn.
        self.search_lock = asyncio.Lock()

    async def _search(
        self, query: str, topic: str = "", reason: str = ""
    ) -> list[Passage]:
        stream = get_stream_writer()
        async with self.search_lock:
            stream({"type": "phase", "phase": "searching"})
            stream({"type": "plan", "queries": [query]})
            results = await run_in_threadpool(self.tracker.search, query)
            stream(
                {
                    "type": "search_status",
                    "queries": [
                        {
                            **detail,
                            "stream": topic,
                            "reason": shorten(reason, width=300, placeholder="…"),
                        }
                        for detail in self.tracker.get_new_queries()
                    ],
                    "total_results": len(self.tracker.all_results),
                }
            )
        return results

    async def start(self, state: ResearchState) -> ResearchState:
        results = await self._search(state["query"])
        evidence = _admit_passages(results, [], self.limits.initial_passages)
        prior = _prior_passages(
            self.tracker.prior_sources,
            state.get("messages", []),
            self.limits.previous_passages,
        )
        evidence += _admit_passages(prior, evidence, len(prior))
        return {"evidence": evidence}

    async def organize(
        self, state: ResearchState, config: RunnableConfig
    ) -> ResearchState:
        question = state["query"]
        history = state.get("messages", [])
        initial = state["evidence"]
        prompt = (
            f"Question: {question}\n\nInitial evidence:\n{_render_evidence(initial)}"
        )
        plan: FollowUpPlan | StreamPlan = await self._request_plan(
            self.opening, prompt, history, config, _INITIAL_PLAN, _STREAM_FORMAT
        )
        if isinstance(plan, StreamPlan):
            return {
                "tasks": [
                    {
                        "order": index,
                        "topic": item.topic,
                        "question": item.query,
                        "history": [],
                        "evidence": [],
                        "searches": [question],
                        "next_query": item.query,
                        "reason": "",
                        "budget": self.limits.searches_per_stream,
                    }
                    for index, item in enumerate(plan.streams)
                ]
            }
        query = self._proposal(plan, [question])
        if not query or self.limits.searches == 1:
            return {"tasks": []}
        return {
            "tasks": [
                {
                    "order": 0,
                    "topic": "",
                    "question": question,
                    "history": history,
                    "evidence": initial,
                    "searches": [question],
                    "next_query": query,
                    "reason": plan.reason,
                    "budget": self.limits.searches - 1,
                }
            ]
        }

    @staticmethod
    def dispatch(state: ResearchState) -> list[Send] | Literal["answer"]:
        tasks = state["tasks"]
        return [Send("research", task) for task in tasks] if tasks else "answer"

    async def research(self, task: StreamTask, config: RunnableConfig) -> ResearchState:
        """Investigate one topic using only this stream's findings for follow-ups."""
        evidence = task["evidence"]
        searches = task["searches"].copy()
        query, reason = task["next_query"], task["reason"]
        for remaining in range(task["budget"] - 1, -1, -1):
            retrieved = await self._search(query, task["topic"], reason)
            recent = _admit_passages(
                retrieved, evidence, self.limits.follow_up_passages
            )
            evidence = evidence + recent
            searches.append(query)
            if remaining == 0:
                break
            prompt = self._follow_up_prompt(task, searches, evidence, recent, remaining)
            plan: FollowUpPlan = await self._request_plan(
                self.planner,
                prompt,
                task["history"],
                config,
                _STREAM_FOLLOW_UP if task["topic"] else _FOLLOW_UP,
                _QUERY_FORMAT,
            )
            query, reason = self._proposal(plan, searches), plan.reason
            if not query:
                break
        return {
            "findings": [
                {"order": task["order"], "topic": task["topic"], "evidence": evidence}
            ]
        }

    @staticmethod
    def _follow_up_prompt(
        task: StreamTask,
        searches: list[str],
        evidence: list[Passage],
        recent: list[Passage],
        remaining: int,
    ) -> str:
        scope = (
            f"Investigate only this stream: {task['topic']}\n" if task["topic"] else ""
        )
        history = "\n".join(searches[1:] if task["topic"] else searches)
        return (
            f"Question: {task['question']}\n{scope}Searches remaining: {remaining}\n"
            f"Searches already run:\n{history}\n\n"
            f"New evidence from the latest search:\n{_render_evidence(recent)}\n\n"
            f"Earlier evidence for this inquiry:\n"
            f"{_render_evidence(evidence[:len(evidence) - len(recent)])}"
        )

    @staticmethod
    def _proposal(plan: FollowUpPlan, searches: list[str]) -> str:
        return next((q for q in plan.queries if _is_new_query(q, searches)), "")

    async def _request_plan(
        self,
        system: str,
        prompt: str,
        history: list[BaseMessage],
        config: RunnableConfig,
        schema: TypeAdapter[_Plan],
        instructions: str,
    ) -> _Plan:
        messages = [SystemMessage(content=system), *history]
        for attempt in range(2):
            request = prompt
            if attempt:
                request += (
                    "\n\nThe previous reply did not match the search plan format. "
                )
                request += instructions
            response = await self.llm.ainvoke(
                [*messages, HumanMessage(content=request)], config=config
            )
            raw = message_text(response).strip()
            fenced = _JSON_FENCE.search(raw)
            try:
                return schema.validate_json(fenced[1] if fenced else raw)
            except ValidationError as exc:
                logger.warning(
                    "Invalid Assistant plan: %s",
                    [
                        (error["loc"], error["type"])
                        for error in exc.errors(
                            include_input=False,
                            include_context=False,
                            include_url=False,
                        )
                    ],
                )
        raise ValueError("The Assistant model could not produce a valid search plan")

    async def answer(
        self, state: ResearchState, config: RunnableConfig
    ) -> ResearchState:
        stream = get_stream_writer()
        stream({"type": "phase", "phase": "synthesizing"})
        findings = sorted(state.get("findings", []), key=lambda entry: entry["order"])
        gathered = (p for f in findings for p in f["evidence"])
        evidence = {p["global_index"]: p for p in (*state["evidence"], *gathered)}
        groups = _render_streams(findings)
        answer = (
            await self._write(
                state["query"],
                state.get("messages", []),
                list(evidence.values()),
                config,
                groups,
            )
            if evidence
            else _NO_EVIDENCE
        )
        stream({"type": "token", "token": answer})
        return {"answer": answer}

    async def _write(
        self,
        query: str,
        history: list[BaseMessage],
        evidence: list[Passage],
        config: RunnableConfig,
        groups: str,
    ) -> str:
        user_prompt = (
            f"Question: {query}\n\n{groups}Retrieved evidence:\n"
            f"{_render_evidence(evidence)}"
        )
        messages = [
            SystemMessage(content=self.writer),
            *history,
            HumanMessage(content=user_prompt),
        ]
        for _ in range(2):
            response = await self.llm.ainvoke(messages, config=config)
            answer = message_text(response).strip()
            if not answer:
                raise ValueError("The Assistant model returned an empty answer")
            invalid = _invalid_citations(answer, evidence)
            if not invalid:
                return answer
            messages.extend(
                [
                    response,
                    HumanMessage(
                        content=(
                            f"These citation labels or ranges are invalid: {', '.join(invalid)}. "
                            "Rewrite the full answer. Cite only labels in the retrieved evidence. "
                            "Remove any claim whose evidence cannot be cited."
                        )
                    ),
                ]
            )
        raise ValueError("The Assistant model could not resolve its citations")


def _render_streams(findings: list[StreamResult]) -> str:
    rows = []
    for finding in findings:
        if not finding["topic"]:
            continue
        labels = ", ".join(str(p["global_index"]) for p in finding["evidence"])
        rows.append(f'- {finding["topic"]}: {labels or "no evidence found"}')
    if not rows:
        return ""
    return "Research streams and their evidence labels:\n" + "\n".join(rows) + "\n\n"


def build_research_workflow(
    llm, tracker, planner: str, writer: str, limits: ResearchLimits, opening: str
):
    workflow = ResearchWorkflow(llm, tracker, planner, writer, limits, opening)
    graph = StateGraph(ResearchState)
    graph.add_node("start", workflow.start)
    graph.add_node("organize", workflow.organize)
    graph.add_node("research", workflow.research)
    graph.add_node("answer", workflow.answer)
    graph.add_edge(START, "start")
    graph.add_edge("start", "organize")
    graph.add_conditional_edges("organize", workflow.dispatch, ["research", "answer"])
    graph.add_edge("research", "answer")
    graph.add_edge("answer", END)
    return graph.compile()
