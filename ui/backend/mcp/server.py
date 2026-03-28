"""MCP server for Evidence Lab.

Registers tools, prompts, and resources on a FastMCP instance.
The HTTP server (http_server.py) handles transport and authentication.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from ui.backend.mcp.audit import log_mcp_call

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Evidence Lab",
    instructions=(
        "Evidence Lab provides semantic search and AI-powered analysis "
        "of evaluation documents from UN agencies, World Bank, and other "
        "development organizations.\n\n"
        "AVAILABLE DATA SOURCES:\n"
        '  - "uneg" (UN Humanitarian Evaluation Reports): ~15,000 evaluation '
        "reports from UNDP, UNICEF, WFP, ILO, FAO, and 20+ UN agencies. "
        "Years 1985-2027.\n"
        '  - "worldbank" (World Bank Fraud and Integrity Reports): '
        "Integrity Vice Presidency investigation reports.\n"
        '  - "unmandates" (UN Mandates Registry): ~4,000 UN General Assembly, '
        "Security Council, and ECOSOC resolutions/decisions.\n\n"
        "AVAILABLE MODEL COMBOS (for ask_assistant):\n"
        '  - "Azure Foundry" (default): GPT-4.1-mini via Azure, '
        "Cohere reranker. Best quality.\n"
        '  - "Huggingface": Qwen 2.5-7B local model. Free, no API key needed.\n'
        '  - "Google Vertex": Gemini 2.5 Flash. Fast, good quality.\n\n'
        "TOOLS:\n"
        "  - search: Find relevant text passages across documents\n"
        "  - get_document: Retrieve full metadata for a specific document\n"
        "  - ask_assistant: Ask a research question and get a synthesized answer"
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
    model_combo: str = "Azure Foundry",
) -> dict:
    """Search evaluation documents using hybrid semantic + keyword search.

    Performs a vector search over chunked documents from UN agencies,
    World Bank, and other development organizations. Returns ranked
    text passages with metadata including document title, organization,
    year, country, and relevance score.

    Args:
        query: Natural language search query. Examples:
            "impact of climate change on food security"
            "gender equality in humanitarian response"
            "What mandates address women peace and security?"
        data_source: Data collection to search. Options:
            "uneg" - UN Humanitarian Evaluation Reports (default)
            "worldbank" - World Bank Fraud and Integrity Reports
            "unmandates" - UN Mandates Registry (resolutions/decisions)
        limit: Maximum number of results to return (1-100, default 20).
        filters: Field filters as {field_name: value} pairs. Available
            fields vary by data source:

            For "uneg" (UN Evaluations):
              organization: UN agency (e.g. "UNDP", "UNICEF", "WFP", "FAO")
              published_year: Year published (e.g. "2024")
              document_type: Type (e.g. "Project Evaluation", "Country Programme")
              country: Country name
              language: Language code (e.g. "English", "French", "Spanish")
              src_geographic_scope: Geographic scope
              tag_sdg: SDG tag (e.g. "SDG1 - No Poverty")
              tag_cross_cutting_theme: Cross-cutting theme

            For "worldbank" (World Bank):
              organization, published_year, document_type, country,
              region, theme, topic, language, tag_sdg

            For "unmandates" (UN Mandates):
              organization: Issuing organ (e.g. "General Assembly")
              published_year: Year adopted
              document_type, document_symbol, subject, tag_sdg

        section_types: Restrict results to specific document sections:
            "executive_summary", "findings", "recommendations",
            "conclusions", "methodology", "context", "lessons_learned",
            "other"
        rerank: Whether to rerank results with a cross-encoder model
            for improved relevance (default True, slower but better).
        recency_boost: Boost more recently published documents in
            relevance scoring (default False).
        field_boost: Apply field-specific importance weighting
            (default True).
        model_combo: Model configuration to use for embeddings and
            reranking. Options: "Azure Foundry" (default, best quality),
            "Huggingface" (free, local), "Google Vertex" (fast).
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
            model_combo=model_combo,
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
            input_params={
                "query": query,
                "data_source": data_source,
                "limit": limit,
                "filters": filters,
            },
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
    """Retrieve full metadata for a specific evaluation document.

    Returns the complete document record including title, organization,
    publication year, abstract, AI-generated summary, table of contents,
    and all available metadata fields. Use this after finding a document
    via the search tool to get more details.

    Args:
        doc_id: The unique document identifier (returned in search results
            as chunk_id or doc_id).
        data_source: Data collection containing the document. Options:
            "uneg" - UN Humanitarian Evaluation Reports (default)
            "worldbank" - World Bank Fraud and Integrity Reports
            "unmandates" - UN Mandates Registry
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
    model_combo: str = "Azure Foundry",
) -> dict:
    """Ask the AI research assistant a question about evaluation documents.

    The assistant searches the document collection, retrieves relevant
    passages, and synthesizes a comprehensive answer with source
    citations. Returns the full answer text and a list of source
    documents referenced.

    Use deep_research=True for complex questions that benefit from
    multiple search passes and deeper analysis (slower but more
    thorough).

    Args:
        query: The research question to answer. Examples:
            "What are the main findings on climate adaptation in Africa?"
            "How effective have school feeding programs been?"
            "Compare approaches to gender mainstreaming across agencies"
        data_source: Data collection to search. Options:
            "uneg" - UN Humanitarian Evaluation Reports (default)
            "worldbank" - World Bank Fraud and Integrity Reports
            "unmandates" - UN Mandates Registry
        deep_research: Enable multi-pass deep research mode for complex
            questions. Uses multiple search queries and iterative
            analysis (default False, slower but more thorough).
        model_combo: LLM model configuration. Options:
            "Azure Foundry" (default) - GPT-4.1-mini, best quality
            "Huggingface" - Qwen 2.5-7B, free/local
            "Google Vertex" - Gemini 2.5 Flash, fast
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
            model_combo=model_combo,
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
                "model_combo": model_combo,
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
    documents on the given topic. The prompt includes context about
    available data sources and suggested search strategies.

    Args:
        topic: The research topic or question to investigate.
            Examples: "climate adaptation", "gender mainstreaming",
            "food security programs"
        data_source: The document collection to search.
            "uneg" (default), "worldbank", or "unmandates"
    """
    from ui.backend.mcp.prompts.research import research_question_prompt

    return research_question_prompt(topic=topic, data_source=data_source)


@mcp.prompt()
def comparative_analysis(topic: str, dimension: str = "organization") -> str:
    """Generate a prompt for comparative analysis across a dimension.

    Creates a prompt that compares how different entities address a
    particular topic across evaluations. Useful for cross-agency,
    cross-country, or temporal comparisons.

    Args:
        topic: The subject to analyze comparatively.
            Examples: "WASH programming", "cash transfer programs"
        dimension: The dimension for comparison. Options:
            "organization" - Compare across UN agencies (default)
            "country" - Compare across countries
            "time_period" - Compare across years/decades
            "sector" - Compare across development sectors
    """
    from ui.backend.mcp.prompts.research import comparative_analysis_prompt

    return comparative_analysis_prompt(topic=topic, dimension=dimension)
