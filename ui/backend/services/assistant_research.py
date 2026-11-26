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
    StrictBool,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from starlette.concurrency import run_in_threadpool
from typing_extensions import Annotated

from ui.backend.services.agent_passages import passage_for_agent
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_citation_model import cited_numbers_in_order
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
_CLARIFY = "What would you like me to look up in the selected dataset?"
_NO_DATASET_EVIDENCE = "NO_DATASET_EVIDENCE"
_LibraryNextStep = Literal["ask", "rephrase", "focus"]
_LIBRARY_NEXT_STEPS: tuple[_LibraryNextStep, ...] = ("ask", "rephrase", "focus")
_MARKDOWN_ATX = re.compile(r"(?m)^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_MARKDOWN_SETEXT = re.compile(r"(?m)^(\S[^\r\n]*)\r?\n {0,3}(?:=+|-+)[ \t]*$")
_SearchQuery = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


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
    query: _SearchQuery


class ContextSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: _SearchQuery
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ContextDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["decline", "clarify"]
    next_step: _LibraryNextStep = "ask"


class GroundingVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: StrictBool


class FollowUpPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[_SearchQuery] = Field(max_length=3)
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
    geographic_scope: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=300)
    ] = ""

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
    geographic_scope: str
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
    initial_search_query: str | None
    messages: list[BaseMessage]
    evidence: list[Passage]
    searches: list[str]
    tasks: list[StreamTask]
    findings: Annotated[list[StreamResult], operator.add]
    answer: str


_Plan = TypeVar("_Plan")
_CONTEXT_PLAN = TypeAdapter(ContextSearch | ContextDisposition)
_GROUNDING_VERDICT = TypeAdapter(GroundingVerdict)
_INITIAL_PLAN: TypeAdapter[FollowUpPlan | StreamPlan] = TypeAdapter(
    FollowUpPlan | StreamPlan
)
_FOLLOW_UP: TypeAdapter[FollowUpPlan] = TypeAdapter(FollowUpPlan)
_STREAM_FOLLOW_UP: TypeAdapter[FollowUpPlan] = TypeAdapter(StreamFollowUpPlan)


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
        contextualizer: str,
        brief_section: bool,
    ):
        if limits.searches < 1 or limits.searches_per_stream < 1:
            raise ValueError("Assistant search budgets must be at least one")
        self.llm = llm
        self.tracker = tracker
        self.planner = planner
        self.opening = opening
        self.contextualizer = contextualizer
        self.brief_section = brief_section
        self.writer = writer
        self.limits = limits
        self.request = assistant_prompt_templates.get_template(
            "assistant_research_request.j2"
        )
        self.grounding_check = assistant_prompt_templates.get_template(
            "assistant_grounding_check.j2"
        ).render()
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

    async def start(
        self, state: ResearchState, config: RunnableConfig
    ) -> ResearchState:
        history = state.get("messages", [])
        question = state["query"]
        query = state.get("initial_search_query")
        reason = ""
        if query is None and history:
            plan: ContextSearch | ContextDisposition = await self._request_json(
                self.contextualizer,
                self.request.render(stage="contextualize", question=question),
                history,
                config,
                _CONTEXT_PLAN,
            )
            if isinstance(plan, ContextDisposition):
                answer = (
                    _CLARIFY
                    if plan.action == "clarify"
                    else _library_refusal(plan.next_step, history)
                )
                get_stream_writer()({"type": "token", "token": answer})
                return {"answer": answer}
            query, reason = plan.query, plan.reason
        if query is None:
            query = question
        results = await self._search(query, reason=reason)
        evidence = _admit_passages(results, [], self.limits.initial_passages)
        prior = _prior_passages(
            self.tracker.prior_sources,
            history,
            self.limits.previous_passages,
        )
        evidence += _admit_passages(prior, evidence, len(prior))
        return {"evidence": evidence, "searches": [query]}

    async def organize(
        self, state: ResearchState, config: RunnableConfig
    ) -> ResearchState:
        question = state["query"]
        searches = state["searches"]
        history = state.get("messages", [])
        initial = state["evidence"]
        prompt = self.request.render(
            stage="organize",
            question=question,
            first_search=searches[0],
            evidence=_render_evidence(initial),
        )
        plan: FollowUpPlan | StreamPlan = await self._request_json(
            self.opening, prompt, history, config, _INITIAL_PLAN
        )
        if isinstance(plan, StreamPlan):
            return {
                "tasks": [
                    {
                        "order": index,
                        "topic": item.topic,
                        "question": item.query,
                        "geographic_scope": plan.geographic_scope,
                        "history": [],
                        "evidence": [],
                        "searches": searches,
                        "next_query": item.query,
                        "reason": "",
                        "budget": self.limits.searches_per_stream,
                    }
                    for index, item in enumerate(plan.streams)
                ]
            }
        query = self._proposal(plan, searches)
        if not query or self.limits.searches == 1:
            return {"tasks": []}
        return {
            "tasks": [
                {
                    "order": 0,
                    "topic": "",
                    "question": question,
                    "geographic_scope": "",
                    "history": history,
                    "evidence": initial,
                    "searches": searches,
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
            plan: FollowUpPlan = await self._request_json(
                self.planner,
                prompt,
                task["history"],
                config,
                _STREAM_FOLLOW_UP if task["topic"] else _FOLLOW_UP,
            )
            query, reason = self._proposal(plan, searches), plan.reason
            if not query:
                break
        return {
            "findings": [
                {"order": task["order"], "topic": task["topic"], "evidence": evidence}
            ]
        }

    def _follow_up_prompt(
        self,
        task: StreamTask,
        searches: list[str],
        evidence: list[Passage],
        recent: list[Passage],
        remaining: int,
    ) -> str:
        history = "\n".join(searches[1:] if task["topic"] else searches)
        return self.request.render(
            stage="follow_up",
            question=task["question"],
            topic=task["topic"],
            geographic_scope=task["geographic_scope"],
            remaining=remaining,
            searches=history,
            recent=_render_evidence(recent),
            evidence=_render_evidence(evidence[: len(evidence) - len(recent)]),
        )

    @staticmethod
    def _proposal(plan: FollowUpPlan, searches: list[str]) -> str:
        return next((q for q in plan.queries if _is_new_query(q, searches)), "")

    async def _request_json(
        self,
        system: str,
        prompt: str,
        history: list[BaseMessage],
        config: RunnableConfig,
        schema: TypeAdapter[_Plan],
    ) -> _Plan:
        messages = [SystemMessage(content=system), *history]
        for attempt in range(2):
            request = prompt
            if attempt:
                request += "\n\n" + self.request.render(stage="retry_plan")
            response = await self.llm.ainvoke(
                [*messages, HumanMessage(content=request)], config=config
            )
            raw = message_text(response).strip()
            fenced = _JSON_FENCE.search(raw)
            try:
                return schema.validate_json(fenced[1] if fenced else raw)
            except ValidationError as exc:
                logger.warning(
                    "Invalid structured Assistant response: %s",
                    [
                        (error["loc"], error["type"])
                        for error in exc.errors(
                            include_input=False,
                            include_context=False,
                            include_url=False,
                        )
                    ],
                )
        raise ValueError(
            "The Assistant model could not produce a valid structured response"
        )

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
        if answer != _NO_EVIDENCE:
            checked = await self._verify_answer(state, answer, evidence, config)
            if not checked:
                answer = _NO_EVIDENCE
        stream({"type": "token", "token": answer})
        return {"answer": answer}

    async def _verify_answer(
        self,
        state: ResearchState,
        answer: str,
        evidence: dict[int, Passage],
        config: RunnableConfig,
    ) -> bool:
        cited = [evidence[index] for index in cited_numbers_in_order(answer)]
        prompt = self.request.render(
            stage="verify",
            question=state["query"],
            search_focus=state["searches"][0],
            answer=answer,
            evidence=_render_evidence(cited),
        )
        verdict: GroundingVerdict = await self._request_json(
            self.grounding_check, prompt, [], config, _GROUNDING_VERDICT
        )
        return verdict.supported

    async def _write(
        self,
        query: str,
        history: list[BaseMessage],
        evidence: list[Passage],
        config: RunnableConfig,
        groups: str,
    ) -> str:
        user_prompt = self.request.render(
            stage="answer",
            question=query,
            streams=groups,
            evidence=_render_evidence(evidence),
        )
        messages = [
            SystemMessage(content=self.writer),
            *history,
            HumanMessage(content=user_prompt),
        ]
        for _ in range(2):
            response = await self.llm.ainvoke(messages, config=config)
            answer = message_text(response).strip()
            if answer == _NO_DATASET_EVIDENCE or not answer:
                return _NO_EVIDENCE
            if self.brief_section:
                answer = _brief_prose(answer)
            invalid = _invalid_citations(answer, evidence)
            if not invalid:
                return answer if cited_numbers_in_order(answer) else _NO_EVIDENCE
            messages.extend(
                [
                    response,
                    HumanMessage(
                        content=self.request.render(
                            stage="retry_citations", invalid=invalid
                        )
                    ),
                ]
            )
        return _NO_EVIDENCE


def _library_refusal(next_step: _LibraryNextStep, history: list[BaseMessage]) -> str:
    """Offer a useful way forward without repeating the previous reply or adding facts."""
    previous = next(
        (message_text(msg) for msg in reversed(history) if isinstance(msg, AIMessage)),
        "",
    )
    template = assistant_prompt_templates.get_template("assistant_library_refusal.j2")
    steps = (next_step, *[step for step in _LIBRARY_NEXT_STEPS if step != next_step])
    return next(
        reply
        for step in steps
        if (reply := template.render(next_step=step).strip()) != previous
    )


def _brief_prose(answer: str) -> str:
    """Keep model-generated heading text and citations as ordinary prose."""
    prose = _MARKDOWN_ATX.sub(r"\1", answer)
    return _MARKDOWN_SETEXT.sub(r"\1\n", prose).strip()


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
    llm,
    tracker,
    planner: str,
    writer: str,
    limits: ResearchLimits,
    opening: str,
    *,
    contextualizer: str,
    brief_section: bool = False,
):
    workflow = ResearchWorkflow(
        llm, tracker, planner, writer, limits, opening, contextualizer, brief_section
    )
    graph = StateGraph(ResearchState)
    graph.add_node("start", workflow.start)
    graph.add_node("organize", workflow.organize)
    graph.add_node("research", workflow.research)
    graph.add_node("answer", workflow.answer)
    graph.add_edge(START, "start")
    graph.add_conditional_edges(
        "start", lambda state: bool(state.get("answer")), {True: END, False: "organize"}
    )
    graph.add_conditional_edges("organize", workflow.dispatch, ["research", "answer"])
    graph.add_edge("research", "answer")
    graph.add_edge("answer", END)
    return graph.compile()
