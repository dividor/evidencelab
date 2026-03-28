"""MCP server for Evidence Lab.

Registers tools, prompts, and resources on a FastMCP instance and
exposes a factory function that returns the Streamable HTTP ASGI app
for mounting on the main FastAPI application.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from ui.backend.mcp.audit import log_mcp_call

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Evidence Lab",
    instructions=(
        "Evidence Lab provides semantic search and AI-powered analysis "
        "of evaluation documents from UN agencies, World Bank, and other "
        "development organizations.  Use the search tool to find relevant "
        "passages, the document tool to retrieve full metadata, and the "
        "assistant tool to ask complex research questions."
    ),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search(
    query: str,
    data_source: Optional[str] = None,
    limit: int = 20,
    filters: Optional[Dict[str, Any]] = None,
    section_types: Optional[List[str]] = None,
    rerank: bool = True,
    recency_boost: bool = False,
    field_boost: bool = True,
) -> dict:
    """Search evaluation documents using hybrid semantic + keyword search.

    Performs a vector search over chunked documents from UN agencies,
    World Bank, and other development organizations.  Returns ranked
    text passages with metadata.

    Args:
        query: Natural language search query.
        data_source: Data collection to search (e.g. "uneg", "worldbank").
            Defaults to the server's primary collection.
        limit: Maximum number of results to return (1-100, default 20).
        filters: Field filters as {field_name: value} pairs.  Supported
            fields depend on the data source (e.g. organization,
            published_year, country, language, document_type).
        section_types: Restrict results to specific section types such as
            ["findings", "recommendations", "lessons_learned"].
        rerank: Whether to rerank results with a cross-encoder (default True).
        recency_boost: Boost more recently published documents.
        field_boost: Apply field-specific boosting heuristics.
    """
    from ui.backend.mcp.tools.search import mcp_search

    t0 = time.monotonic()
    auth_info: dict = {"type": "unknown", "user_id": "unknown"}
    status = "ok"
    error_msg = None

    try:
        result = await mcp_search(
            query=query,
            data_source=data_source,
            limit=limit,
            filters=filters,
            section_types=section_types,
            rerank=rerank,
            recency_boost=recency_boost,
            field_boost=field_boost,
        )
        return result.model_dump()
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        raise
    finally:
        duration_ms = (time.monotonic() - t0) * 1000
        log_mcp_call(
            tool_name="search",
            auth_info=auth_info,
            client_ip="unknown",
            input_params={"query": query, "data_source": data_source, "limit": limit},
            output_summary=f"status={status}",
            duration_ms=duration_ms,
            status=status,
            error_message=error_msg,
        )


@mcp.tool()
async def get_document(
    doc_id: str,
    data_source: Optional[str] = None,
) -> dict:
    """Retrieve metadata for a specific evaluation document.

    Returns the full document record including title, organization,
    publication year, abstract, AI-generated summary, and all
    available metadata fields.

    Args:
        doc_id: The unique document identifier.
        data_source: Data collection containing the document
            (e.g. "uneg", "worldbank").
    """
    from ui.backend.mcp.tools.document import mcp_get_document

    t0 = time.monotonic()
    auth_info: dict = {"type": "unknown", "user_id": "unknown"}
    status = "ok"
    error_msg = None

    try:
        result = await mcp_get_document(doc_id=doc_id, data_source=data_source)
        return result.model_dump()
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        raise
    finally:
        duration_ms = (time.monotonic() - t0) * 1000
        log_mcp_call(
            tool_name="get_document",
            auth_info=auth_info,
            client_ip="unknown",
            input_params={"doc_id": doc_id, "data_source": data_source},
            output_summary=f"status={status}",
            duration_ms=duration_ms,
            status=status,
            error_message=error_msg,
        )


@mcp.tool()
async def ask_assistant(
    query: str,
    data_source: Optional[str] = None,
    deep_research: bool = False,
) -> dict:
    """Ask the AI research assistant a question about evaluation documents.

    The assistant searches the document collection, retrieves relevant
    passages, and synthesizes a comprehensive answer with source
    citations.  Use deep_research=True for complex questions that
    benefit from multiple search passes and deeper analysis.

    Args:
        query: The research question to answer.
        data_source: Data collection to search (e.g. "uneg", "worldbank").
        deep_research: Enable multi-pass deep research mode for complex
            questions (slower but more thorough).
    """
    from ui.backend.mcp.tools.assistant import mcp_ask_assistant

    t0 = time.monotonic()
    auth_info: dict = {"type": "unknown", "user_id": "unknown"}
    status = "ok"
    error_msg = None

    try:
        result = await mcp_ask_assistant(
            query=query,
            data_source=data_source,
            deep_research=deep_research,
        )
        return result.model_dump()
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        raise
    finally:
        duration_ms = (time.monotonic() - t0) * 1000
        log_mcp_call(
            tool_name="ask_assistant",
            auth_info=auth_info,
            client_ip="unknown",
            input_params={
                "query": query,
                "data_source": data_source,
                "deep_research": deep_research,
            },
            output_summary=f"status={status}",
            duration_ms=duration_ms,
            status=status,
            error_message=error_msg,
        )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@mcp.prompt()
def research_question(topic: str, data_source: str = "uneg") -> str:
    """Generate a structured research prompt for investigating a topic.

    Creates a prompt that guides thorough research across evaluation
    documents on the given topic.

    Args:
        topic: The research topic or question to investigate.
        data_source: The document collection to search (default "uneg").
    """
    from ui.backend.mcp.prompts.research import research_question_prompt

    return research_question_prompt(topic=topic, data_source=data_source)


@mcp.prompt()
def comparative_analysis(topic: str, dimension: str = "organization") -> str:
    """Generate a prompt for comparative analysis across a dimension.

    Creates a prompt that compares how different entities address a
    particular topic across evaluations.

    Args:
        topic: The subject to analyze comparatively.
        dimension: The dimension for comparison (e.g. "organization",
            "country", "time_period", "sector").
    """
    from ui.backend.mcp.prompts.research import comparative_analysis_prompt

    return comparative_analysis_prompt(topic=topic, dimension=dimension)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_mcp_app():
    """Create the MCP ASGI app for mounting on FastAPI.

    Returns a Starlette/ASGI application that handles the MCP
    Streamable HTTP protocol at the mount point.
    """
    # Use create_streamable_http_app directly with path="/"
    # so the handler sits at the root of the sub-app.
    # The parent FastAPI app mounts us at /mcp.
    from fastmcp.server.http import create_streamable_http_app

    return create_streamable_http_app(
        mcp,
        streamable_http_path="/",
        stateless_http=False,
        json_response=False,
    )
