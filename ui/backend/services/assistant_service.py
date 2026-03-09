"""
Research Assistant service.

High-level service wrapping the LangGraph research agent, providing
SSE streaming and conversation persistence.
"""

import logging
import sys
import uuid as uuid_mod
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage

from ui.backend.services.assistant_graph import ResearchState, build_research_graph

logger = logging.getLogger(__name__)


def _get_llm(model_key=None, temperature=None, max_tokens=None):
    """Get LLM instance via the factory."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from utils.llm_factory import get_llm

    return get_llm(
        model=model_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _get_langsmith_trace_url(run_id: uuid_mod.UUID) -> Optional[str]:
    """Get LangSmith trace URL if tracing is enabled."""
    try:
        from ui.backend.services.llm_service import get_langsmith_trace_url

        return get_langsmith_trace_url(run_id)
    except Exception:
        return None


def _build_conversation_messages(
    query: str,
    conversation_messages: Optional[List[Dict[str, str]]] = None,
) -> List:
    """Build LangChain message objects from conversation history."""
    messages: List = []
    if conversation_messages:
        for msg in conversation_messages[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=query))
    return messages


def _build_initial_state(
    query: str,
    messages: List,
    data_source: Optional[str],
    max_iterations: int,
) -> ResearchState:
    """Build the initial ResearchState for the graph."""
    return {
        "messages": messages,
        "query": query,
        "search_queries": [],
        "search_results": [],
        "synthesis": "",
        "reflection": "",
        "iteration": 0,
        "max_iterations": max_iterations,
        "sources": [],
        "should_continue": True,
        "data_source": data_source,
    }


def _events_for_node(
    node_name: str,
    node_output: Dict[str, Any],
    initial_state: ResearchState,
) -> List[Dict[str, Any]]:
    """Generate SSE events for a given graph node output."""
    events: List[Dict[str, Any]] = []

    if node_name == "plan":
        queries = node_output.get("search_queries", [])
        events.append({"type": "plan", "queries": queries})
        events.append({"type": "phase", "phase": "searching"})

    elif node_name == "search":
        results = node_output.get("search_results", [])
        events.append(
            {
                "type": "search_status",
                "query": ", ".join(initial_state.get("search_queries", [])),
                "result_count": len(results),
            }
        )
        events.append({"type": "phase", "phase": "synthesizing"})

    elif node_name == "synthesize":
        synthesis = node_output.get("synthesis", "")
        sources = node_output.get("sources", [])
        events.append({"type": "token", "token": synthesis})
        if sources:
            events.append({"type": "sources", "sources": sources})
        events.append({"type": "phase", "phase": "reflecting"})

    elif node_name == "reflect":
        if node_output.get("should_continue", False):
            events.append({"type": "phase", "phase": "planning"})

    return events


def _build_done_event(run_id: uuid_mod.UUID) -> Dict[str, Any]:
    """Build the completion event with optional LangSmith trace URL."""
    done_event: Dict[str, Any] = {
        "type": "done",
        "messageId": str(uuid_mod.uuid4()),
    }
    langsmith_url = _get_langsmith_trace_url(run_id)
    if langsmith_url:
        done_event["langsmith_trace_url"] = langsmith_url
    return done_event


async def stream_research_response(
    query: str,
    data_source: Optional[str] = None,
    model_key: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_iterations: int = 3,
    conversation_messages: Optional[List[Dict[str, str]]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream a research response via SSE events.

    Runs the LangGraph research agent and yields structured events
    as the agent progresses through plan/search/synthesize/reflect phases.
    """
    run_id = uuid_mod.uuid4()

    try:
        llm = _get_llm(
            model_key=model_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        graph = build_research_graph(llm)
        messages = _build_conversation_messages(query, conversation_messages)
        initial_state = _build_initial_state(
            query, messages, data_source, max_iterations
        )

        yield {"type": "phase", "phase": "planning"}

        for step_output in graph.stream(initial_state, config={"run_id": str(run_id)}):
            for node_name, node_output in step_output.items():
                for event in _events_for_node(node_name, node_output, initial_state):
                    yield event

        yield _build_done_event(run_id)

    except Exception as exc:
        logger.error("Research stream error: %s", exc, exc_info=True)
        yield {"type": "error", "error": str(exc)}
