"""
Research Assistant service.

High-level service wrapping the deepagents research agent, providing
SSE streaming and conversation persistence.
"""

import asyncio
import logging
import sys
import uuid as uuid_mod
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage

from ui.backend.services.assistant_graph import (
    _get_assistant_config,
    build_deep_research_agent,
    build_research_agent,
)

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


def _extract_search_queries(msg) -> List[str]:
    """Extract search_documents queries from an AI message's tool calls."""
    queries: List[str] = []
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            if tc.get("name") == "search_documents":
                query = tc.get("args", {}).get("query", "")
                if query:
                    queries.append(query)
    return queries


def _extract_task_delegations(msg) -> List[str]:
    """Extract sub-agent task delegations from an AI message's tool calls."""
    tasks: List[str] = []
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            if tc.get("name") == "task":
                args = tc.get("args", {})
                # deepagents task tool uses "description" param, not "task"
                desc = args.get("description", "") or args.get("task", "") or str(args)
                tasks.append(desc)
    return tasks


def _has_any_tool_calls(msg) -> bool:
    """Check if an AI message has any tool calls (search, write_todos, etc)."""
    return bool(getattr(msg, "tool_calls", None))


def _process_agent_output(node_output: Dict) -> Dict[str, Any]:
    """Process output from the model node.

    Only treat a message as final response text if it has NO tool calls.
    The deepagents framework has built-in tools (write_todos, etc.) that
    produce tool calls we don't surface, but their presence means the
    model is still working, not producing the final answer.

    In deep research mode, the coordinator delegates via the ``task``
    tool.  We surface these as ``task_delegations`` so the UI can show
    a "researching" phase.
    """
    result: Dict[str, Any] = {
        "tool_queries": [],
        "task_delegations": [],
        "response_text": "",
    }
    messages = node_output.get("messages", [])
    for msg in messages:
        search_queries = _extract_search_queries(msg)
        if search_queries:
            result["tool_queries"].extend(search_queries)
            continue
        task_delegations = _extract_task_delegations(msg)
        if task_delegations:
            result["task_delegations"].extend(task_delegations)
        elif _has_any_tool_calls(msg):
            # Model called non-search tools (write_todos, etc.) — skip
            pass
        elif hasattr(msg, "content") and msg.content:
            result["response_text"] = msg.content
    return result


def _is_duplicate_or_subset(new_text: str, prev_text: str) -> bool:
    """Check if new_text is identical or a subset of prev_text (normalized)."""
    if not new_text or not prev_text:
        return False
    norm_new = " ".join(new_text.split())
    norm_prev = " ".join(prev_text.split())
    return norm_new == norm_prev or norm_new in norm_prev


async def _yield_sources_and_done(
    tracker: Any, run_id: uuid_mod.UUID
) -> AsyncGenerator[Dict[str, Any], None]:
    """Yield final sources (if any) followed by the done event."""
    sources = tracker.get_sources()
    if sources:
        yield {"type": "sources", "sources": sources}
    yield _build_done_event(run_id)


async def _handle_stream_error(
    exc: Exception, tracker: Any, run_id: uuid_mod.UUID
) -> AsyncGenerator[Dict[str, Any], None]:
    """Yield error or graceful completion events for a stream exception."""
    is_recursion = "recursion" in str(exc).lower()
    if is_recursion:
        logger.warning("Agent hit recursion limit: %s", exc)
    else:
        logger.error("Research stream error: %s", exc, exc_info=True)

    if is_recursion and tracker and tracker.all_results:
        async for event in _yield_sources_and_done(tracker, run_id):
            yield event
    else:
        yield {"type": "error", "error": str(exc)}


async def stream_research_response(
    query: str,
    data_source: Optional[str] = None,
    model_key: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_iterations: int = 3,
    conversation_messages: Optional[List[Dict[str, str]]] = None,
    reranker_model: Optional[str] = None,
    search_settings: Optional[Dict[str, Any]] = None,
    system_prompt_override: Optional[str] = None,
    deep_research: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream a research response via SSE events.

    Runs the deepagents research agent and yields structured events
    as the agent searches, plans, and synthesizes its response.

    Uses a buffer-and-emit-last strategy for token events: the latest
    synthesis text is buffered and only yielded when a non-token event
    arrives or the stream ends.  This prevents duplicate or intermediate
    synthesis text from reaching the client.

    In deep research mode, the search tool pushes real-time search
    progress events to a shared asyncio Queue so the client sees each
    search query as it happens (instead of waiting for the whole
    sub-agent to finish).
    """
    run_id = uuid_mod.uuid4()
    tracker = None

    try:
        llm = _get_llm(
            model_key=model_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        builder = build_deep_research_agent if deep_research else build_research_agent
        agent, tracker = builder(
            llm,
            data_source,
            reranker_model,
            search_settings,
            system_prompt_override=system_prompt_override,
        )
        messages = _build_conversation_messages(query, conversation_messages)
        cfg = _get_assistant_config()
        if deep_research:
            deep_cfg = cfg.get("deep_research", {})
            recursion_limit = deep_cfg.get("recursion_limit", 100)
        else:
            recursion_limit = cfg.get("recursion_limit", 12)

        yield {"type": "phase", "phase": "planning"}

        if deep_research:
            async for event in _stream_deep_research(
                agent, tracker, messages, run_id, recursion_limit
            ):
                yield event
        else:
            async for event in _stream_normal_research(
                agent, tracker, messages, run_id, recursion_limit
            ):
                yield event

        async for event in _yield_sources_and_done(tracker, run_id):
            yield event

    except Exception as exc:
        async for event in _handle_stream_error(exc, tracker, run_id):
            yield event


async def _stream_normal_research(
    agent: Any,
    tracker: Any,
    messages: List,
    run_id: uuid_mod.UUID,
    recursion_limit: int,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream events from a normal (non-deep) research agent."""
    token_buffer = ""
    async for step_output in agent.astream(
        {"messages": messages},
        config={"run_id": str(run_id), "recursion_limit": recursion_limit},
        stream_mode="updates",
    ):
        for event in _events_from_step(step_output, tracker):
            if event.get("type") == "token":
                new_text = event["token"]
                if not _is_duplicate_or_subset(new_text, token_buffer):
                    token_buffer = new_text
            else:
                if token_buffer:
                    yield {"type": "token", "token": token_buffer}
                    token_buffer = ""
                yield event

    if token_buffer:
        yield {"type": "token", "token": token_buffer}


_SENTINEL = object()


async def _stream_deep_research(
    agent: Any,
    tracker: Any,
    messages: List,
    run_id: uuid_mod.UUID,
    recursion_limit: int,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream deep research events with real-time search progress.

    The sub-agent's searches happen inside a single "tools" node, so
    the normal ``astream`` loop blocks until the sub-agent finishes.
    To surface search progress in real time, the tracker pushes events
    to a shared asyncio Queue.  We run the agent stream in a background
    task and consume from the queue, yielding events as they arrive.
    """
    event_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    tracker.set_event_queue(event_queue, loop)

    agent_error: Optional[Exception] = None

    async def _run_agent() -> None:
        nonlocal agent_error
        try:
            async for step_output in agent.astream(
                {"messages": messages},
                config={
                    "run_id": str(run_id),
                    "recursion_limit": recursion_limit,
                },
                stream_mode="updates",
            ):
                for event in _events_from_step(step_output, tracker):
                    await event_queue.put(event)
        except Exception as exc:
            agent_error = exc
        finally:
            await event_queue.put(_SENTINEL)

    agent_task = asyncio.create_task(_run_agent())

    token_buffer = ""
    try:
        while True:
            event = await event_queue.get()
            if event is _SENTINEL:
                break
            etype = event.get("type")
            if etype == "token":
                new_text = event["token"]
                if not _is_duplicate_or_subset(new_text, token_buffer):
                    token_buffer = new_text
            else:
                if token_buffer:
                    yield {"type": "token", "token": token_buffer}
                    token_buffer = ""
                yield event
    finally:
        await agent_task

    if token_buffer:
        yield {"type": "token", "token": token_buffer}

    if agent_error is not None:
        raise agent_error


def _events_from_step(
    step_output: Dict[str, Any],
    tracker: Any,
) -> List[Dict[str, Any]]:
    """Generate SSE events from a single graph step output.

    The deepagents framework uses "model" as the LLM node name and "tools"
    for tool execution.  Middleware nodes (e.g. "TodoListMiddleware.before_model")
    are ignored.
    """
    events: List[Dict[str, Any]] = []

    for node_name, node_output in step_output.items():
        if node_name == "model":
            agent_result = _process_agent_output(node_output)
            if agent_result["tool_queries"]:
                events.append({"type": "phase", "phase": "searching"})
                events.append(
                    {
                        "type": "plan",
                        "queries": agent_result["tool_queries"],
                    }
                )
            elif agent_result["task_delegations"]:
                # Deep research coordinator delegated to sub-agent(s)
                events.append({"type": "phase", "phase": "searching"})
            elif agent_result["response_text"]:
                events.append(
                    {
                        "type": "token",
                        "token": agent_result["response_text"],
                    }
                )

        elif node_name == "tools":
            # Only emit NEW search queries (not previously emitted ones)
            new_queries = tracker.get_new_queries()
            if new_queries:
                events.append(
                    {
                        "type": "search_status",
                        "queries": new_queries,
                        "total_results": len(tracker.all_results),
                    }
                )
            # When searches are done, transition to synthesizing phase
            # so the user sees "Synthesizing answer..." while the LLM works
            if tracker.all_results:
                events.append({"type": "phase", "phase": "synthesizing"})

        else:
            logger.debug("Skipping middleware node: %s", node_name)

    return events
