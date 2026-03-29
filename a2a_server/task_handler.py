"""A2A task handler — executes tasks using the same services as the MCP tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from a2a_server.schemas import (
    Artifact,
    DataPart,
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

logger = logging.getLogger(__name__)

_ASSISTANT_TIMEOUT_SECONDS = 120


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_query(message: Message) -> str:
    """Pull the text from the first text part of a message."""
    for part in message.parts:
        if isinstance(part, TextPart) and part.text.strip():
            return part.text.strip()
    raise ValueError("No text content found in message")


def _extract_skill(message: Message) -> str:
    """Determine which skill to invoke from the message metadata or content."""
    if message.metadata:
        skill = message.metadata.get("skill")
        if skill:
            return skill
    # Heuristic: if the message starts with "search" it's a search skill
    query = _extract_query(message)
    if re.match(r"^search\b", query, re.IGNORECASE):
        return "search"
    return "research"


async def handle_task(task_id: str, message: Message) -> Task:
    """Execute a task synchronously and return the completed Task."""
    query = _extract_query(message)
    skill = _extract_skill(message)

    try:
        if skill == "search":
            artifacts = await _run_search(query, message.metadata)
        else:
            artifacts = await _run_research(query, message.metadata)

        return Task(
            id=task_id,
            status=TaskStatus(state=TaskState.COMPLETED, timestamp=_now()),
            artifacts=artifacts,
            history=[message],
        )
    except Exception as exc:
        logger.error("A2A task %s failed: %s", task_id, exc)
        return Task(
            id=task_id,
            status=TaskStatus(
                state=TaskState.FAILED,
                timestamp=_now(),
                message=Message(
                    role="agent",
                    parts=[TextPart(text=f"Task failed: {exc}")],
                ),
            ),
            history=[message],
        )


async def handle_task_streaming(
    task_id: str, message: Message
) -> AsyncGenerator[str, None]:
    """Execute a task and yield SSE-formatted A2A events.

    Yields lines suitable for an SSE response:
        data: <json>\\n\\n
    """
    query = _extract_query(message)
    skill = _extract_skill(message)

    # Notify client we're working
    working_event = TaskStatusUpdateEvent(
        id=task_id,
        status=TaskStatus(state=TaskState.WORKING, timestamp=_now()),
        final=False,
    )
    yield _sse("TaskStatusUpdateEvent", working_event.model_dump())

    try:
        if skill == "search":
            artifacts = await _run_search(query, message.metadata)
        else:
            # Stream tokens from the assistant
            async for sse_line in _run_research_streaming(
                task_id, query, message.metadata
            ):
                yield sse_line
            return

        for artifact in artifacts:
            artifact_event = TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
            yield _sse("TaskArtifactUpdateEvent", artifact_event.model_dump())

        final_event = TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(state=TaskState.COMPLETED, timestamp=_now()),
            final=True,
        )
        yield _sse("TaskStatusUpdateEvent", final_event.model_dump())

    except Exception as exc:
        logger.error("A2A streaming task %s failed: %s", task_id, exc)
        error_event = TaskStatusUpdateEvent(
            id=task_id,
            status=TaskStatus(
                state=TaskState.FAILED,
                timestamp=_now(),
                message=Message(
                    role="agent",
                    parts=[TextPart(text=f"Task failed: {exc}")],
                ),
            ),
            final=True,
        )
        yield _sse("TaskStatusUpdateEvent", error_event.model_dump())


# ---------------------------------------------------------------------------
# Skill implementations — reuse the same tool modules as MCP
# ---------------------------------------------------------------------------


async def _run_research(
    query: str, metadata: Optional[Dict[str, Any]]
) -> List[Artifact]:
    """Run the research assistant and return artifacts."""
    from mcp_server.tools.assistant import mcp_ask_assistant

    meta = metadata or {}
    data_source = meta.get("data_source")
    deep_research = bool(meta.get("deep_research", False))
    model_combo = meta.get("model_combo", "Azure Foundry")

    response = await mcp_ask_assistant(
        query=query,
        data_source=data_source,
        deep_research=deep_research,
        model_combo=model_combo,
    )

    parts: List[Any] = [TextPart(text=response.answer)]

    # Include structured citation data as a data part
    if response.citations:
        parts.append(
            DataPart(
                data={
                    "citations": [c.model_dump() for c in response.citations],
                    "references": response.references,
                    "sources": response.sources,
                },
                mimeType="application/json",
            )
        )

    return [
        Artifact(
            name="research_response",
            description="Synthesised research answer with citations",
            parts=parts,
            lastChunk=True,
        )
    ]


async def _run_research_streaming(
    task_id: str,
    query: str,
    metadata: Optional[Dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """Stream tokens from the assistant, yielding SSE events."""
    from pipeline.db import UI_MODEL_COMBOS
    from ui.backend.services.assistant_service import stream_research_response

    meta = metadata or {}
    data_source = meta.get("data_source")
    deep_research = bool(meta.get("deep_research", False))
    model_combo = meta.get("model_combo", "Azure Foundry")

    combo = UI_MODEL_COMBOS.get(model_combo, {})
    assistant_cfg = combo.get("assistant_model") or {}
    model_key = (
        assistant_cfg.get("model") if isinstance(assistant_cfg, dict) else assistant_cfg
    )
    reranker_model = combo.get("reranker_model")

    answer_text = ""
    sources: List[Dict[str, Any]] = []
    token_events: List[str] = []

    async def _consume() -> None:
        nonlocal answer_text, sources
        async for event in stream_research_response(
            query=query,
            data_source=data_source,
            deep_research=deep_research,
            model_key=model_key,
            reranker_model=reranker_model,
        ):
            event_type = event.get("type")
            if event_type == "token":
                token = event.get("token", "")
                answer_text += token
                chunk_artifact = Artifact(
                    name="research_response",
                    parts=[TextPart(text=token)],
                    index=0,
                    append=True,
                    lastChunk=False,
                )
                chunk_event = TaskArtifactUpdateEvent(
                    id=task_id, artifact=chunk_artifact
                )
                token_events.append(
                    _sse("TaskArtifactUpdateEvent", chunk_event.model_dump())
                )
            elif event_type == "sources":
                sources.extend(event.get("sources", []))
            elif event_type == "error":
                raise RuntimeError(event.get("error", "Unknown assistant error"))

    try:
        await asyncio.wait_for(_consume(), timeout=_ASSISTANT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        if not answer_text:
            raise RuntimeError(
                f"Assistant timed out after {_ASSISTANT_TIMEOUT_SECONDS}s"
            )

    for evt in token_events:
        yield evt

    # Build citation metadata from sources
    from mcp_server.tools.assistant import _build_citations_from_sources

    citations, references = await _build_citations_from_sources(sources, data_source)

    # Final artifact with complete text + citations
    final_artifact = Artifact(
        name="research_response",
        description="Synthesised research answer with citations",
        parts=[
            TextPart(text=answer_text),
            DataPart(
                data={
                    "citations": [c.model_dump() for c in citations],
                    "references": references,
                    "sources": sources,
                },
                mimeType="application/json",
            ),
        ],
        index=0,
        append=False,
        lastChunk=True,
    )
    final_artifact_event = TaskArtifactUpdateEvent(id=task_id, artifact=final_artifact)
    yield _sse("TaskArtifactUpdateEvent", final_artifact_event.model_dump())

    final_status = TaskStatusUpdateEvent(
        id=task_id,
        status=TaskStatus(state=TaskState.COMPLETED, timestamp=_now()),
        final=True,
    )
    yield _sse("TaskStatusUpdateEvent", final_status.model_dump())


async def _run_search(query: str, metadata: Optional[Dict[str, Any]]) -> List[Artifact]:
    """Run semantic search and return artifacts."""
    from mcp_server.tools.search import mcp_search

    meta = metadata or {}
    data_source = meta.get("data_source")
    limit = int(meta.get("limit", 10))
    filters = meta.get("filters")
    model_combo = meta.get("model_combo", "Azure Foundry")

    if isinstance(filters, str):
        filters = json.loads(filters)

    response = await mcp_search(
        query=query,
        data_source=data_source,
        limit=limit,
        filters=filters,
        model_combo=model_combo,
    )

    # Summary text part
    summary_lines = [f"Found {response.total} results for: {query}", ""]
    for r in response.results:
        summary_lines.append(f"**{r.title}** ({r.organization}, {r.year})")
        summary_lines.append(f"Score: {r.score:.3f} | Page: {r.page_num}")
        summary_lines.append(r.text[:300] + ("..." if len(r.text) > 300 else ""))
        summary_lines.append("")

    if response.references:
        summary_lines.append("## References")
        summary_lines.extend(response.references)

    return [
        Artifact(
            name="search_results",
            description=f"{response.total} search results",
            parts=[
                TextPart(text="\n".join(summary_lines)),
                DataPart(
                    data={
                        "total": response.total,
                        "query": response.query,
                        "results": [r.model_dump() for r in response.results],
                        "citations": [c.model_dump() for c in response.citations],
                        "references": response.references,
                    },
                    mimeType="application/json",
                ),
            ],
            lastChunk=True,
        )
    ]


def _sse(event_type: str, data: Dict[str, Any]) -> str:
    """Format a server-sent event line."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
