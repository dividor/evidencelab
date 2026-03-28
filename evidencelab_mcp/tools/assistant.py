"""MCP AI research assistant tool — ask questions about evaluation documents."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from evidencelab_mcp.schemas import MCPAssistantResponse

logger = logging.getLogger(__name__)

# Maximum time to wait for the assistant to produce a complete response.
_ASSISTANT_TIMEOUT_SECONDS = 120


async def mcp_ask_assistant(
    query: str,
    data_source: Optional[str] = None,
    deep_research: bool = False,
    model_combo: str = "Azure Foundry",
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
        from pipeline.db import UI_MODEL_COMBOS

        combo = UI_MODEL_COMBOS.get(model_combo, {})
        assistant_model_config = combo.get("assistant_model")
        reranker_model = combo.get("reranker_model")

        async for event in stream_research_response(
            query=query,
            data_source=data_source,
            deep_research=deep_research,
            assistant_model_config=assistant_model_config,
            reranker_model=reranker_model,
        ):
            event_type = event.get("type")
            if event_type == "token":
                # The last token event contains the full synthesized text
                answer_text = event.get("token", "")
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

    return MCPAssistantResponse(
        answer=answer_text,
        sources=sources,
        query=query,
        data_source=data_source,
    )
