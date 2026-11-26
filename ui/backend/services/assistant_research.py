"""The shared LangGraph workflow for Assistant and Deep Research."""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from starlette.concurrency import run_in_threadpool
from typing_extensions import Annotated

from ui.backend.services.agent_passages import passage_for_agent
from utils.llm_factory import message_text

Passage = dict[str, Any]
_CITATION = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")
_SEARCH_TERMS_EXCLUDED = frozenset(
    "a an and the of in for by on what which how are does do that is were".split()
)
_JSON_FENCE = re.compile(
    r"\s*`{3}(?:json)?\s*(.*?)\s*`{3}\s*", re.DOTALL | re.IGNORECASE
)
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


class ResearchState(TypedDict, total=False):
    query: str
    messages: list[BaseMessage]
    next_query: str
    searches: list[str]
    evidence: list[Passage]
    answer: str


class FollowUpPlan(BaseModel):
    queries: list[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
        ]
    ] = Field(max_length=3)


def _search_terms(query: str) -> set[str]:
    return set(re.findall(r"\w+", query.casefold())) - _SEARCH_TERMS_EXCLUDED


def _is_new_query(candidate: str, previous: list[str]) -> bool:
    terms = _search_terms(candidate)
    if not terms:
        return False
    for query in previous:
        earlier = _search_terms(query)
        if earlier and len(terms & earlier) / len(terms | earlier) >= 0.8:
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

    def __init__(self, llm, tracker, planner: str, writer: str, limits: ResearchLimits):
        if limits.searches < 1:
            raise ValueError("Assistant search budget must be at least one")
        self.llm = llm
        self.tracker = tracker
        self.planner = planner
        self.writer = writer
        self.limits = limits

    async def search(self, state: ResearchState) -> ResearchState:
        query = state.get("next_query") or state["query"]
        searches = state.get("searches", [])
        stream = get_stream_writer()
        stream({"type": "phase", "phase": "searching"})
        stream({"type": "plan", "queries": [query]})
        results = await run_in_threadpool(self.tracker.search, query)
        evidence = state.get("evidence", [])
        limit = (
            self.limits.follow_up_passages if searches else self.limits.initial_passages
        )
        admitted = _admit_passages(results, evidence, limit)
        evidence = evidence + admitted
        if not searches:
            prior = _prior_passages(
                self.tracker.prior_sources,
                state.get("messages", []),
                self.limits.previous_passages,
            )
            evidence += _admit_passages(prior, evidence, len(prior))
        stream(
            {
                "type": "search_status",
                "queries": self.tracker.get_new_queries(),
                "total_results": len(self.tracker.all_results),
            }
        )
        return {"evidence": evidence, "searches": [*searches, query]}

    def after_search(self, state: ResearchState) -> str:
        return "answer" if len(state["searches"]) >= self.limits.searches else "plan"

    async def plan(self, state: ResearchState, config: RunnableConfig) -> ResearchState:
        history = "\n".join(state["searches"])
        evidence = _render_evidence(state["evidence"])
        remaining = self.limits.searches - len(state["searches"])
        prompt = (
            f"Question: {state['query']}\nSearches remaining: {remaining}\n"
            f"Searches already run:\n{history}\n\nRetrieved evidence:\n{evidence}"
        )
        plan = await self._request_plan(prompt, state.get("messages", []), config)
        next_query = next(
            (q for q in plan.queries if _is_new_query(q, state["searches"])), ""
        )
        return {"next_query": next_query}

    async def _request_plan(
        self, prompt: str, history: list[BaseMessage], config: RunnableConfig
    ) -> FollowUpPlan:
        messages = [SystemMessage(content=self.planner), *history]
        for attempt in range(2):
            request = prompt
            if attempt:
                request += (
                    "\n\nThe previous reply did not match the search plan format. "
                    'Return only a JSON object like {"queries":["a focused search"]} '
                    'or {"queries":[]} when no more searches are needed.'
                )
            response = await self.llm.ainvoke(
                [*messages, HumanMessage(content=request)], config=config
            )
            raw = message_text(response).strip()
            fenced = _JSON_FENCE.fullmatch(raw)
            try:
                return FollowUpPlan.model_validate_json(fenced[1] if fenced else raw)
            except ValidationError:
                continue
        raise ValueError("The Assistant model could not produce a valid search plan")

    def after_plan(self, state: ResearchState) -> str:
        return "search" if state["next_query"] else "answer"

    async def answer(
        self, state: ResearchState, config: RunnableConfig
    ) -> ResearchState:
        stream = get_stream_writer()
        stream({"type": "phase", "phase": "synthesizing"})
        messages = state.get("messages", [])
        evidence = state["evidence"]
        answer = (
            await self._write(state["query"], messages, evidence, config)
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
    ) -> str:
        user_prompt = (
            f"Question: {query}\n\nRetrieved evidence:\n{_render_evidence(evidence)}"
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


def build_research_workflow(
    llm, tracker, planner: str, writer: str, limits: ResearchLimits
):
    workflow = ResearchWorkflow(llm, tracker, planner, writer, limits)
    graph = StateGraph(ResearchState)
    graph.add_node("search", workflow.search)
    graph.add_node("plan", workflow.plan)
    graph.add_node("answer", workflow.answer)
    graph.add_edge(START, "search")
    graph.add_conditional_edges("search", workflow.after_search, ["plan", "answer"])
    graph.add_conditional_edges("plan", workflow.after_plan, ["search", "answer"])
    graph.add_edge("answer", END)
    return graph.compile()
