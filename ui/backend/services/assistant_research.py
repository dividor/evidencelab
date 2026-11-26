"""The shared LangGraph workflow for Assistant and Deep Research."""

import asyncio
import logging
import operator
import re
from collections import Counter
from dataclasses import dataclass
from functools import partial
from textwrap import shorten
from typing import Literal, TypedDict, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import TypeAdapter, ValidationError
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
from ui.backend.services.assistant_research_plan import (
    CONTEXT_PLAN,
    DEEP_PLAN,
    FOLLOW_UP,
    INITIAL_PLAN,
    STREAM_FOLLOW_UP,
    ContextDisposition,
    ContextSearch,
    FollowUpPlan,
    LibraryNextStep,
    StreamPlan,
    is_new_query,
    verified_geographic_scope,
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

_JSON_FENCE = re.compile(r"`{3}(?:json)?\s*(\{.*?\})\s*`{3}", re.DOTALL | re.IGNORECASE)
_NO_EVIDENCE = (
    "I couldn’t find evidence in the selected collection to answer this question."
)
_CLARIFY = "What would you like me to look up in the selected dataset?"
_NO_DATASET_EVIDENCE = "NO_DATASET_EVIDENCE"
_LIBRARY_NEXT_STEPS: tuple[LibraryNextStep, ...] = ("ask", "rephrase", "focus")


@dataclass(frozen=True)
class ResearchLimits:
    """Bound the number of searches and the evidence handed to the writer."""

    searches: int
    initial_passages: int = 12
    follow_up_passages: int = 6
    previous_passages: int = 6
    searches_per_stream: int = 2


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
    target_words: int | None


class StreamResult(TypedDict):
    order: int
    topic: str
    evidence: list[Passage]


class ResearchState(TypedDict, total=False):
    query: str
    survey_only: bool
    require_deep_plan: bool
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
    structured_brief: bool
    verified_draft: str
    answer_evidence: dict[int, Passage]
    brief_focus: str | None


_Plan = TypeVar("_Plan")


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
                CONTEXT_PLAN,
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
        target_words = state.get("brief_target_words")
        require_deep_plan = state.get("require_deep_plan", False)
        history = state.get("messages", [])
        initial = state["evidence"]
        prompt = self.request.render(
            stage="organize",
            question=question,
            first_search=searches[0],
            evidence=render_evidence(initial),
            brief_section=self.brief_section,
            brief_focus=brief_focus,
            target_words=target_words,
            require_deep_plan=require_deep_plan,
        )
        plan: FollowUpPlan | StreamPlan = await self._request_json(
            self.opening,
            prompt,
            history,
            config,
            DEEP_PLAN if require_deep_plan else INITIAL_PLAN,
        )
        if isinstance(plan, StreamPlan):
            scope = verified_geographic_scope(
                plan.geographic_scope, question, searches[0]
            )
            return {
                "tasks": [
                    {
                        "order": index,
                        "topic": item.topic,
                        "question": item.query,
                        "geographic_scope": scope,
                        "history": [],
                        "evidence": [],
                        "searches": searches,
                        "next_query": item.query,
                        "reason": "",
                        "budget": self.limits.searches_per_stream,
                        "brief_focus": brief_focus,
                        "target_words": target_words,
                    }
                    for index, item in enumerate(plan.streams)
                ]
            }
        if self.limits.searches == 1:
            return {"tasks": []}
        query, reason = await self._next_search(
            plan, searches, question, history, config
        )
        if not query:
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
                    "reason": reason,
                    "budget": self.limits.searches - 1,
                    "brief_focus": brief_focus,
                    "target_words": target_words,
                }
            ]
        }

    @staticmethod
    def after_searches(state: ResearchState) -> Literal["answer", "__end__"]:
        return END if state.get("survey_only") else "answer"

    @staticmethod
    def dispatch(state: ResearchState) -> list[Send] | Literal["answer", "__end__"]:
        tasks = state["tasks"]
        if tasks:
            return [Send("research", task) for task in tasks]
        return ResearchWorkflow.after_searches(state)

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
                STREAM_FOLLOW_UP if task["topic"] else FOLLOW_UP,
            )
            query, reason = await self._next_search(
                plan, searches, task["question"], task["history"], config
            )
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
            target_words=task["target_words"],
            recent=render_evidence(recent),
            evidence=render_evidence(evidence[: len(evidence) - len(recent)]),
        )

    @staticmethod
    def _proposal(plan: FollowUpPlan, searches: list[str]) -> str:
        return next((q for q in plan.queries if is_new_query(q, searches)), "")

    async def _next_search(
        self,
        plan: FollowUpPlan,
        searches: list[str],
        question: str,
        history: list[BaseMessage],
        config: RunnableConfig,
    ) -> tuple[str, str]:
        query = self._proposal(plan, searches)
        if query or not plan.queries or not plan.reason:
            return query, plan.reason
        prompt = self.request.render(
            stage="distinct_search",
            question=question,
            searches=searches,
            reason=plan.reason,
        )
        revised: FollowUpPlan = await self._request_json(
            self.planner, prompt, history, config, STREAM_FOLLOW_UP
        )
        return self._proposal(revised, searches), revised.reason

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
        request = prompt
        model = self.llm if llm is None else llm
        for _ in range(2):
            response = await model.ainvoke(
                [*messages, HumanMessage(content=request)], config=config
            )
            raw = message_text(response).strip()
            fenced = _JSON_FENCE.search(raw)
            try:
                return schema.validate_json(fenced[1] if fenced else raw)
            except ValidationError as exc:
                errors = [
                    (error["loc"], error["type"])
                    for error in exc.errors(
                        include_input=False, include_context=False, include_url=False
                    )
                ]
                logger.warning(
                    "Invalid structured Assistant response (stop=%s, output_tokens=%s): %s",
                    response.response_metadata.get("finish_reason"),
                    (getattr(response, "usage_metadata", None) or {}).get(
                        "output_tokens"
                    ),
                    errors,
                )
                request = (
                    prompt
                    + "\n\n"
                    + self.request.render(
                        stage="retry_plan", validation_errors=errors[:12]
                    )
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
        if self.brief_section and self.brief_section.mode == "generate":
            section = await write_grounded_brief(
                state["query"],
                state["searches"][0],
                self.writer,
                evidence,
                config,
                self.llm,
                self.citation_request if self.check_citations else None,
                self.brief_section,
                target_words=state.get("brief_target_words"),
            )
            return {"draft": section or _NO_EVIDENCE, "structured_brief": True}
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
        if answer != _NO_EVIDENCE and not state.get("structured_brief"):
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
            if review.issues or self.check_citations:
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


def _library_refusal(next_step: LibraryNextStep, history: list[BaseMessage]) -> str:
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
    graph.add_conditional_edges(
        "organize", workflow.dispatch, ["research", "answer", END]
    )
    graph.add_conditional_edges("research", workflow.after_searches, ["answer", END])
    graph.add_edge("answer", "check_citations")
    graph.add_conditional_edges(
        "check_citations",
        lambda state: bool(state.get("answer")),
        {True: END, False: "answer"},
    )
    return graph.compile()
