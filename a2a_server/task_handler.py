"""A2A task handler — executes tasks using the same services as the MCP tools."""

from __future__ import annotations

import asyncio
import json
import logging
import os
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


def _load_allowed_data_sources() -> frozenset[str]:
    """Read allowed data_source values from config.json at import time.

    Returns a frozenset of valid ``data_subdir`` strings (e.g. ``"uneg"``,
    ``"worldbank"``).  If config.json is missing or malformed an empty set is
    returned and validation is skipped — fail-open is intentional here because
    a missing config file is a deployment issue, not an injection attempt.
    """
    try:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(config_path) as fh:
            config = json.load(fh)
        sources = config.get("datasources", {})
        return frozenset(
            ds.get("data_subdir") for ds in sources.values() if ds.get("data_subdir")
        )
    except FileNotFoundError:
        logger.warning("config.json not found — data_source validation skipped")
        return frozenset()
    except Exception as exc:
        logger.error("Failed to load allowed data sources from config.json: %s", exc)
        return frozenset()


# Loaded once at startup; empty set means validation is skipped.
_ALLOWED_DATA_SOURCES: frozenset[str] = _load_allowed_data_sources()


def _validate_data_source(data_source: str | None) -> None:
    """Raise ValueError if *data_source* is not in the allowed set.

    No-op when *data_source* is None/empty or when the allowed set is empty
    (config not loaded).
    """
    if not data_source or not _ALLOWED_DATA_SOURCES:
        return
    if data_source not in _ALLOWED_DATA_SOURCES:
        raise ValueError(
            f"Invalid data_source {data_source!r}. "
            f"Allowed values: {sorted(_ALLOWED_DATA_SOURCES)}"
        )


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
            contextId=task_id,
            status=TaskStatus(state=TaskState.COMPLETED, timestamp=_now()),
            artifacts=artifacts,
            history=[message],
        )
    except Exception as exc:
        logger.error("A2A task %s failed: %s", task_id, exc)
        return Task(
            id=task_id,
            contextId=task_id,
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
    task_id: str, message: Message, rpc_id: Any
) -> AsyncGenerator[str, None]:
    """Execute a task and yield SSE-formatted A2A events.

    Each yielded line is a full JSON-RPC response envelope per the A2A spec:
        data: {"jsonrpc":"2.0","id":<rpc_id>,"result":{...}}\\n\\n
    """
    query = _extract_query(message)
    skill = _extract_skill(message)

    # Notify client we're working
    working_event = TaskStatusUpdateEvent(
        taskId=task_id,
        contextId=task_id,
        status=TaskStatus(state=TaskState.WORKING, timestamp=_now()),
        final=False,
    )
    yield _sse_rpc(rpc_id, working_event.model_dump())

    try:
        if skill == "search":
            artifacts = await _run_search(query, message.metadata)
        else:
            # Stream tokens from the assistant
            async for sse_line in _run_research_streaming(
                task_id, query, message.metadata, rpc_id
            ):
                yield sse_line
            return

        for artifact in artifacts:
            artifact_event = TaskArtifactUpdateEvent(
                taskId=task_id, contextId=task_id, artifact=artifact
            )
            yield _sse_rpc(rpc_id, artifact_event.model_dump())

        final_event = TaskStatusUpdateEvent(
            taskId=task_id,
            contextId=task_id,
            status=TaskStatus(state=TaskState.COMPLETED, timestamp=_now()),
            final=True,
        )
        yield _sse_rpc(rpc_id, final_event.model_dump())

    except Exception as exc:
        logger.error("A2A streaming task %s failed: %s", task_id, exc)
        error_event = TaskStatusUpdateEvent(
            taskId=task_id,
            contextId=task_id,
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
        yield _sse_rpc(rpc_id, error_event.model_dump())


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
    _validate_data_source(data_source)
    deep_research = bool(meta.get("deep_research", False))
    model_combo = meta.get("model_combo")

    response = await mcp_ask_assistant(
        query=query,
        data_source=data_source,
        deep_research=deep_research,
        model_combo=model_combo,
    )

    parts: List[Any] = [TextPart(text=response.answer)]

    # Always include a structured data part so callers can inspect citation metadata.
    # The citations list may be empty when no matching documents were found.
    parts.append(
        DataPart(
            data={
                "citations": [c.model_dump() for c in response.citations],
                "references": response.references,
                "sources": response.sources,
            },
        )
    )

    return [
        Artifact(
            name="research_response",
            description="Synthesised research answer with citations",
            parts=parts,
        )
    ]


async def _run_research_streaming(
    task_id: str,
    query: str,
    metadata: Optional[Dict[str, Any]],
    rpc_id: Any = None,
) -> AsyncGenerator[str, None]:
    """Stream tokens from the assistant, yielding SSE events."""
    from pipeline.db import UI_MODEL_COMBOS, get_default_model_combo
    from ui.backend.services.assistant_service import stream_research_response

    meta = metadata or {}
    data_source = meta.get("data_source")
    _validate_data_source(data_source)
    deep_research = bool(meta.get("deep_research", False))
    model_combo = meta.get("model_combo")

    resolved_combo = model_combo or get_default_model_combo()
    combo = UI_MODEL_COMBOS.get(resolved_combo, {})
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
                )
                chunk_event = TaskArtifactUpdateEvent(
                    taskId=task_id, contextId=task_id, artifact=chunk_artifact
                )
                token_events.append(_sse_rpc(rpc_id, chunk_event.model_dump()))
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
            ),
        ],
    )
    final_artifact_event = TaskArtifactUpdateEvent(
        taskId=task_id, contextId=task_id, artifact=final_artifact
    )
    yield _sse_rpc(rpc_id, final_artifact_event.model_dump())

    final_status = TaskStatusUpdateEvent(
        taskId=task_id,
        contextId=task_id,
        status=TaskStatus(state=TaskState.COMPLETED, timestamp=_now()),
        final=True,
    )
    yield _sse_rpc(rpc_id, final_status.model_dump())


async def _run_search(query: str, metadata: Optional[Dict[str, Any]]) -> List[Artifact]:
    """Run semantic search and return artifacts."""
    from mcp_server.tools.search import mcp_search

    meta = metadata or {}
    data_source = meta.get("data_source")
    _validate_data_source(data_source)
    limit = int(meta.get("limit", 10))
    filters = meta.get("filters")
    model_combo = meta.get("model_combo")

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
                ),
            ],
        )
    ]


def _sse_rpc(rpc_id: Any, result: Dict[str, Any]) -> str:
    """Format an SSE line as a JSON-RPC response envelope per the A2A spec."""
    response = {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    return f"data: {json.dumps(response)}\n\n"
