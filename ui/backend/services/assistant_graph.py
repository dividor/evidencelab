"""
LangGraph research assistant agent.

Implements a reflective deep research pattern:
  plan -> search -> synthesize -> reflect -> (continue? -> plan | END)

Uses LangGraph for the state machine and langgraph-checkpoint-postgres
for thread-based conversation memory.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph

from ui.backend.services.assistant_tools import search_documents

logger = logging.getLogger(__name__)

# Jinja2 environment for prompt templates
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)


def _load_template(name: str):
    """Load a Jinja2 template by name."""
    return _jinja_env.get_template(name)


class ResearchState(TypedDict):
    """State for the research assistant graph."""

    messages: List[BaseMessage]
    query: str
    search_queries: List[str]
    search_results: List[Dict[str, Any]]
    synthesis: str
    reflection: str
    iteration: int
    max_iterations: int
    sources: List[Dict[str, Any]]
    should_continue: bool
    data_source: Optional[str]


def _get_conversation_context(messages: List[BaseMessage], max_msgs: int = 6) -> str:
    """Extract recent conversation context for planning."""
    recent = messages[-(max_msgs):]
    lines = []
    for msg in recent:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        content = msg.content
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def plan_node(state: ResearchState, llm) -> Dict[str, Any]:
    """Decompose user query into focused search sub-queries."""
    template = _load_template("assistant_plan.j2")
    context = _get_conversation_context(state["messages"])

    prompt = template.render(
        query=state["query"],
        conversation_context=context if context else None,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    # Parse JSON array of search queries
    try:
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        queries = json.loads(content)
        if not isinstance(queries, list):
            queries = [state["query"]]
    except (json.JSONDecodeError, IndexError):
        logger.warning("Failed to parse plan queries, using original: %s", content)
        queries = [state["query"]]

    # Limit to 3 queries
    queries = queries[:3]
    logger.info("Plan node: %d queries for %r", len(queries), state["query"][:60])

    return {"search_queries": queries}


def search_node(state: ResearchState) -> Dict[str, Any]:
    """Execute search queries against the document database."""
    all_results = list(state.get("search_results", []))
    seen_ids = {r.get("chunk_id") for r in all_results}

    for query in state["search_queries"]:
        results = search_documents(
            query=query,
            data_source=state.get("data_source"),
            limit=20,
        )
        for r in results:
            cid = r.get("chunk_id", "")
            if cid not in seen_ids:
                all_results.append(r)
                seen_ids.add(cid)

    # Sort by score descending, keep top results
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    max_results = state.get("max_iterations", 3) * 20
    all_results = all_results[:max_results]

    logger.info(
        "Search node: %d unique results from %d queries",
        len(all_results),
        len(state["search_queries"]),
    )

    return {"search_results": all_results}


def synthesize_node(state: ResearchState, llm) -> Dict[str, Any]:
    """Synthesize a cited answer from search results."""
    template = _load_template("assistant_synthesize.j2")

    # Use top results for synthesis
    top_results = state["search_results"][:30]

    prompt = template.render(
        query=state["query"],
        search_results=top_results,
        previous_synthesis=(
            state.get("synthesis") if state.get("iteration", 0) > 0 else None
        ),
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    synthesis = response.content.strip()

    # Build source references
    sources = []
    seen_doc_ids = set()
    for r in top_results:
        doc_id = r.get("doc_id", "")
        if doc_id and doc_id not in seen_doc_ids:
            sources.append(
                {
                    "chunkId": r.get("chunk_id", ""),
                    "docId": doc_id,
                    "title": r.get("title", ""),
                    "text": (
                        (r.get("text", "")[:200] + "...")
                        if len(r.get("text", "")) > 200
                        else r.get("text", "")
                    ),
                    "score": r.get("score", 0.0),
                    "page": r.get("page"),
                }
            )
            seen_doc_ids.add(doc_id)

    logger.info("Synthesize node: %d chars, %d sources", len(synthesis), len(sources))

    return {"synthesis": synthesis, "sources": sources}


def reflect_node(state: ResearchState, llm) -> Dict[str, Any]:
    """Evaluate answer completeness and decide if another iteration needed."""
    template = _load_template("assistant_reflect.j2")
    current_iter = state.get("iteration", 0) + 1
    max_iter = state.get("max_iterations", 3)

    # If we've hit the max, don't bother reflecting
    if current_iter >= max_iter:
        logger.info("Reflect node: max iterations reached (%d)", max_iter)
        return {
            "iteration": current_iter,
            "should_continue": False,
            "reflection": "Maximum iterations reached.",
        }

    prompt = template.render(
        query=state["query"],
        synthesis=state.get("synthesis", ""),
        num_results=len(state.get("search_results", [])),
        iteration=current_iter,
        max_iterations=max_iter,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    # Parse reflection JSON
    try:
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        reflection = json.loads(content)
    except (json.JSONDecodeError, IndexError):
        logger.warning("Failed to parse reflection, stopping: %s", content)
        reflection = {"should_continue": False, "reasoning": content}

    should_continue = reflection.get("should_continue", False)
    additional_queries = reflection.get("additional_queries", [])

    logger.info(
        "Reflect node: iter=%d, continue=%s, reason=%s",
        current_iter,
        should_continue,
        reflection.get("reasoning", "")[:100],
    )

    update: Dict[str, Any] = {
        "iteration": current_iter,
        "should_continue": should_continue,
        "reflection": reflection.get("reasoning", ""),
    }

    if should_continue and additional_queries:
        update["search_queries"] = additional_queries[:2]

    return update


def should_continue(state: ResearchState) -> str:
    """Routing function: continue iterating or end."""
    if state.get("should_continue", False):
        return "search"
    return END


def build_research_graph(llm) -> StateGraph:
    """
    Build the LangGraph research agent graph.

    Args:
        llm: LangChain chat model instance

    Returns:
        Compiled StateGraph
    """
    graph = StateGraph(ResearchState)

    # Add nodes with LLM bound
    graph.add_node("plan", lambda state: plan_node(state, llm))
    graph.add_node("search", search_node)
    graph.add_node("synthesize", lambda state: synthesize_node(state, llm))
    graph.add_node("reflect", lambda state: reflect_node(state, llm))

    # Define edges
    graph.set_entry_point("plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "synthesize")
    graph.add_edge("synthesize", "reflect")
    graph.add_conditional_edges("reflect", should_continue)

    return graph.compile()
