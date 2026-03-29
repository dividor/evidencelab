"""MCP AI research assistant tool — ask questions about evaluation documents."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from mcp_server.schemas import MCPAssistantResponse, MCPCitation

logger = logging.getLogger(__name__)

_CITATION_GUIDANCE = (
    "IMPORTANT: You MUST include ALL of the following in your response:\n"
    "1. Every factual claim MUST have at least one clickable inline citation: "
    "[[1]](url), [[2]](url). Renumber sequentially from 1 in your response order.\n"
    "2. Include a References section (each ref on its OWN line) for every item "
    "you cited.\n"
    "3. When reporting counts from a text/semantic query, caveat that the total "
    "is approximate — semantic search matches variations and related terms.\n"
    "Do NOT omit inline citations. Do NOT put multiple references on one line."
)

# Maximum time to wait for the assistant to produce a complete response.
_ASSISTANT_TIMEOUT_SECONDS = 120


async def mcp_ask_assistant(
    query: str,
    data_source: Optional[str] = None,
    deep_research: bool = False,
    model_combo: Optional[str] = None,
) -> MCPAssistantResponse:
    """Ask the AI research assistant a question about evaluation documents.

    The assistant searches the document collection, retrieves relevant
    passages, and synthesizes a comprehensive answer with source
    citations.  Use ``deep_research=True`` for complex questions that
    benefit from multiple search passes and deeper analysis.

    Args:
        query: The research question to answer.
        data_source: Data collection to search (e.g. "uneg", "worldbank").
        deep_research: Enable multi-pass deep research mode for complex
            questions (slower but more thorough).

    Returns:
        MCPAssistantResponse with the synthesized answer and sources.
    """
    from ui.backend.services.assistant_service import stream_research_response

    answer_text = ""
    sources: List[Dict[str, Any]] = []

    async def _consume_stream():
        nonlocal answer_text, sources
        from pipeline.db import UI_MODEL_COMBOS, get_default_model_combo

        resolved = model_combo or get_default_model_combo()
        combo = UI_MODEL_COMBOS.get(resolved, {})
        assistant_cfg = combo.get("assistant_model") or {}
        model_key = (
            assistant_cfg.get("model")
            if isinstance(assistant_cfg, dict)
            else assistant_cfg
        )
        reranker_model = combo.get("reranker_model")

        async for event in stream_research_response(
            query=query,
            data_source=data_source,
            deep_research=deep_research,
            model_key=model_key,
            reranker_model=reranker_model,
        ):
            event_type = event.get("type")
            if event_type == "token":
                answer_text += event.get("token", "")
            elif event_type == "sources":
                sources = event.get("sources", [])
            elif event_type == "error":
                error_msg = event.get("error", "Unknown error")
                raise RuntimeError(f"Assistant error: {error_msg}")

    try:
        await asyncio.wait_for(
            _consume_stream(),
            timeout=_ASSISTANT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "MCP assistant timed out after %ds for query: %s",
            _ASSISTANT_TIMEOUT_SECONDS,
            query[:100],
        )
        if not answer_text:
            raise RuntimeError(
                f"Assistant timed out after {_ASSISTANT_TIMEOUT_SECONDS}s"
            )
        # Partial answer is still useful — return what we have

    citations, references = await _build_citations_from_sources(sources, data_source)

    return MCPAssistantResponse(
        answer=answer_text,
        sources=sources,
        citations=citations,
        references=references,
        citation_guidance=_CITATION_GUIDANCE,
        query=query,
        data_source=data_source,
    )


async def _build_citations_from_sources(
    sources: List[Dict[str, Any]],
    data_source: Optional[str],
) -> tuple[List[MCPCitation], List[str]]:
    """Build citation and reference lists from raw assistant sources.

    Shared by both MCP (ask_assistant) and the A2A task handler so
    citation logic is not duplicated.
    """
    doc_metadata: Dict[str, Dict[str, Any]] = {}
    unique_doc_ids = {s.get("docId", "") for s in sources if s.get("docId")}
    if unique_doc_ids:
        from mcp_server.tools.document import mcp_get_document

        for did in unique_doc_ids:
            try:
                doc = await mcp_get_document(doc_id=did, data_source=data_source)
                doc_metadata[did] = doc.metadata
                doc_metadata[did]["_title"] = doc.title
                doc_metadata[did]["_org"] = doc.organization or ""
                doc_metadata[did]["_year"] = doc.year or ""
            except Exception:
                logger.debug("Could not fetch metadata for doc %s", did)

    citations: List[MCPCitation] = []
    references: List[str] = []
    for i, src in enumerate(sources, 1):
        doc_id = src.get("docId", "")
        meta = doc_metadata.get(doc_id, {})
        title = src.get("title") or meta.get("_title", f"Document {i}")
        org = meta.get("_org", "")
        year = meta.get("_year", "")
        report_url = meta.get("report_url", "")
        page_num = src.get("page")
        url = (
            report_url
            or f"{os.environ.get('APP_BASE_URL', 'https://evidencelab.ai')}/search"
        )
        if page_num and url and "#" not in url:
            url = f"{url}#page={page_num}"
        label_parts = [org, year]
        label_suffix = ", ".join(p for p in label_parts if p)
        formatted_title = f"{title} ({label_suffix})" if label_suffix else title
        citations.append(
            MCPCitation(
                label=f"[{i}]",
                url=url,
                title=formatted_title,
                organization=org or None,
                year=year or None,
            )
        )
        references.append(f"[{i}] [{formatted_title}]({url})")

    return citations, references
