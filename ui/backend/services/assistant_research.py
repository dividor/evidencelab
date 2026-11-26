"""The shared LangGraph workflow for Assistant and Deep Research."""

import asyncio
import logging
import operator
import re
from collections import Counter
from dataclasses import dataclass
from functools import partial
from textwrap import shorten
from typing import Literal, Self, TypedDict, TypeVar

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

from ui.backend.auth.schemas import BriefSectionPrompt
from ui.backend.services.assistant_brief_writer import write_grounded_brief
from ui.backend.services.assistant_grounding import (
    InvalidAssistantResponse,
    Passage,
    ReviewRequest,
    check_research_draft,
    invalid_citations,
    prior_evidence_passages,
    render_evidence,
    render_evidence_streams,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_citation_model import cited_numbers_in_order
from ui.backend.services.brief_section_prompt import (
    BRIEF_SECTION_SCOPE,
    BriefSectionScope,
    apply_brief_section_scope,
    brief_section_research_focus,
    brief_section_scope_request,
    build_section_prompt,
)
from utils.llm_factory import message_text

logger = logging.getLogger(__name__)

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
    brief_focus: str | None


class StreamResult(TypedDict):
    order: int
    topic: str
    evidence: list[Passage]


class ResearchState(TypedDict, total=False):
    query: str
    brief_target_words: int | None
    initial_search_query: str | None
    messages: list[BaseMessage]
    evidence: list[Passage]
    searches: list[str]
    tasks: list[StreamTask]
    findings: Annotated[list[StreamResult], operator.add]
    answer: str
    draft: str
    correction: list[str]
    brief_final_repair: bool
    grounded_section: bool
    verified_draft: str
    answer_evidence: dict[int, Passage]
    brief_focus: str | None


_Plan = TypeVar("_Plan")
_CONTEXT_PLAN = TypeAdapter(ContextSearch | ContextDisposition)
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
        brief_section: BriefSectionPrompt | None,
        check_citations: bool,
        citation_llm,
    ):
        if limits.searches < 1 or limits.searches_per_stream < 1:
            raise ValueError("Assistant search budgets must be at least one")
        self.llm = llm
        self.tracker = tracker
        self.planner = planner
        self.opening = opening
        self.contextualizer = contextualizer
        self.brief_section = brief_section
        self.check_citations = check_citations
        self.citation_request: ReviewRequest = partial(
            self._request_json, llm=citation_llm
        )
        self.writer = writer
        self.limits = limits
        self.request = assistant_prompt_templates.get_template(
            "assistant_research_request.j2"
        )
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
        prior = prior_evidence_passages(
            self.tracker.prior_sources,
            history,
            self.limits.previous_passages,
        )
        evidence += _admit_passages(prior, evidence, len(prior))
        started: ResearchState = {"evidence": evidence, "searches": [query]}
        if self.brief_section is not None:
            section = await self._scope_brief(self.brief_section, config)
            started["query"] = build_section_prompt(section)
            started["brief_focus"] = brief_section_research_focus(section)
        return started

    async def _scope_brief(
        self, section: BriefSectionPrompt, config: RunnableConfig
    ) -> BriefSectionPrompt:
        if not section.instructions or not section.instructions.strip():
            return section
        system, prompt, common, choices = brief_section_scope_request(section)
        result: BriefSectionScope = await self._request_json(
            system, prompt, [], config, BRIEF_SECTION_SCOPE
        )
        logger.info(
            "Brief section selected %s from %d author instruction blocks",
            result.selected,
            len(choices),
        )
        return apply_brief_section_scope(section, common, choices, result)

    async def organize(
        self, state: ResearchState, config: RunnableConfig
    ) -> ResearchState:
        searches = state["searches"]
        question = searches[0] if self.brief_section else state["query"]
        brief_focus = state.get("brief_focus")
        history = state.get("messages", [])
        initial = state["evidence"]
        prompt = self.request.render(
            stage="organize",
            question=question,
            first_search=searches[0],
            evidence=render_evidence(initial),
            brief_section=self.brief_section,
            brief_focus=brief_focus,
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
                        "brief_focus": brief_focus,
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
                    "brief_focus": brief_focus,
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
            brief_focus=task["brief_focus"],
            recent=render_evidence(recent),
            evidence=render_evidence(evidence[: len(evidence) - len(recent)]),
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
        *,
        llm=None,
    ) -> _Plan:
        messages = [SystemMessage(content=system), *history]
        for attempt in range(2):
            request = prompt
            if attempt:
                request += "\n\n" + self.request.render(stage="retry_plan")
            model = self.llm if llm is None else llm
            response = await model.ainvoke(
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
        raise InvalidAssistantResponse(
            "The Assistant model could not produce a valid structured response"
        )

    async def draft_answer(
        self, state: ResearchState, config: RunnableConfig
    ) -> ResearchState:
        stream = get_stream_writer()
        stream({"type": "phase", "phase": "synthesizing"})
        findings = sorted(state.get("findings", []), key=lambda entry: entry["order"])
        gathered = (p for f in findings for p in f["evidence"])
        evidence = {p["global_index"]: p for p in (*state["evidence"], *gathered)}
        if (
            self.brief_section
            and self.brief_section.mode == "generate"
            and self.check_citations
        ):
            section = await write_grounded_brief(
                state["query"],
                state["searches"][0],
                self.writer,
                evidence,
                config,
                self.llm,
                self.citation_request,
                self.brief_section,
                target_words=state.get("brief_target_words"),
            )
            return {"draft": section or _NO_EVIDENCE, "grounded_section": True}
        draft = (
            await self._write(
                state,
                list(evidence.values()),
                config,
                render_evidence_streams(findings),
            )
            if evidence
            else _NO_EVIDENCE
        )
        return {"draft": draft, "answer_evidence": evidence}

    async def check_answer(
        self, state: ResearchState, config: RunnableConfig
    ) -> ResearchState:
        answer = state["draft"]
        if answer != _NO_EVIDENCE and not state.get("grounded_section"):
            if self.check_citations:
                get_stream_writer()({"type": "phase", "phase": "checking_citations"})
            review = await check_research_draft(
                answer,
                state["query"],
                state["searches"][0],
                state["answer_evidence"],
                config,
                self._request_json,
                brief_section=self.brief_section is not None,
                check_citations=self.check_citations,
                citation_request=self.citation_request,
            )
            corrected = bool(state.get("correction"))
            if review.revision(
                brief_section=self.brief_section is not None,
                corrected=corrected,
                can_repair_verified_prose=self.check_citations
                and not state.get("brief_final_repair"),
                has_verified_draft=bool(state.get("verified_draft")),
            ):
                return {
                    "correction": review.issues,
                    "draft": review.revision_base or answer,
                    "verified_draft": review.supported_text,
                    "brief_final_repair": corrected,
                }
            if review.issues:
                answer = review.supported_text or _NO_EVIDENCE
        if answer == _NO_EVIDENCE and state.get("verified_draft"):
            answer = state["verified_draft"]
        if self.brief_section is not None and answer == _NO_EVIDENCE:
            get_stream_writer()({"type": "brief_section_unwritten"})
        else:
            get_stream_writer()({"type": "token", "token": answer})
        return {"answer": answer}

    async def _write(
        self,
        state: ResearchState,
        evidence: list[Passage],
        config: RunnableConfig,
        groups: str,
    ) -> str:
        user_prompt = self.request.render(
            stage="answer",
            question=state["query"],
            streams=groups,
            evidence=render_evidence(evidence),
            correction=state.get("correction"),
            draft=state.get("draft"),
            brief_section=self.brief_section is not None,
            brief_final_repair=state.get("brief_final_repair"),
        )
        messages = [
            SystemMessage(content=self.writer),
            *state.get("messages", []),
            HumanMessage(content=user_prompt),
        ]
        for _ in range(2):
            response = await self.llm.ainvoke(messages, config=config)
            answer = message_text(response).strip()
            if answer == _NO_DATASET_EVIDENCE or not answer:
                return _NO_EVIDENCE
            invalid = invalid_citations(answer, evidence)
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


def build_research_workflow(
    llm,
    tracker,
    planner: str,
    writer: str,
    limits: ResearchLimits,
    opening: str,
    *,
    contextualizer: str,
    brief_section: BriefSectionPrompt | None = None,
    check_citations: bool = True,
    citation_llm=None,
):
    workflow = ResearchWorkflow(
        llm,
        tracker,
        planner,
        writer,
        limits,
        opening,
        contextualizer,
        brief_section,
        check_citations,
        citation_llm,
    )
    graph = StateGraph(ResearchState)
    graph.add_node("start", workflow.start)
    graph.add_node("organize", workflow.organize)
    graph.add_node("research", workflow.research)
    graph.add_node("answer", workflow.draft_answer)
    graph.add_node("check_citations", workflow.check_answer)
    graph.add_edge(START, "start")
    graph.add_conditional_edges(
        "start", lambda state: bool(state.get("answer")), {True: END, False: "organize"}
    )
    graph.add_conditional_edges("organize", workflow.dispatch, ["research", "answer"])
    graph.add_edge("research", "answer")
    graph.add_edge("answer", "check_citations")
    graph.add_conditional_edges(
        "check_citations",
        lambda state: bool(state.get("answer")),
        {True: END, False: "answer"},
    )
    return graph.compile()
