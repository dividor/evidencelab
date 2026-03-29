"""MCP server for Evidence Lab.

Registers tools, prompts, and resources on a FastMCP instance.
The HTTP server (http_server.py) handles transport and authentication.
"""

import json
import logging
import time
from typing import Annotated, Any, List, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_server.audit import log_mcp_call, request_auth, request_client_ip
from mcp_server.schemas import MCPDocumentResponse, MCPSearchResponse

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    """Load config.json from project root."""
    import json as _json
    from pathlib import Path

    config_path = Path(__file__).resolve().parents[1] / "config.json"
    with open(config_path) as f:
        return _json.load(f)


def _data_source_description() -> str:
    """Build data_source field description from config.json."""
    try:
        cfg = _load_config()
        sources = cfg.get("datasources", {})
        entries = []
        for name, conf in sources.items():
            subdir = conf.get("data_subdir", "")
            entries.append(f'"{subdir}" ({name})')
        first_subdir = list(sources.values())[0].get("data_subdir", "uneg")
        return (
            "Data collection to search. Options: "
            + ", ".join(entries)
            + f'. Default: "{first_subdir}".'
        )
    except Exception:
        return (
            "Data collection to search. Options: "
            '"uneg" (UN Humanitarian Evaluation Reports, default), '
            '"worldbank" (World Bank Fraud and Integrity Reports), '
            '"unmandates" (UN Mandates Registry)'
        )


def _filters_description() -> str:
    """Build filters field description from config.json."""
    try:
        cfg = _load_config()
        sources = cfg.get("datasources", {})
        parts = ["JSON object with filter field/value pairs. " "All fields optional. "]
        for name, conf in sources.items():
            subdir = conf.get("data_subdir", "")
            fields = conf.get("default_filter_fields", {})
            if fields:
                field_names = [k for k in fields if k != "title"]
                parts.append(f'For "{subdir}": {", ".join(field_names)}. ')
        parts.append(
            'Examples: {"organization": "UNDP", "published_year": "2024"} '
            'or {"tag_sdg": "SDG5 - Gender Equality", "country": "Kenya"}. '
            "TIP: Set include_facets=True to discover all available "
            "filter values and counts."
        )
        return "".join(parts)
    except Exception:
        return (
            "JSON object with filter field/value pairs. "
            'Example: {"organization": "UNDP", "published_year": "2024"}. '
            "TIP: Set include_facets=True to discover available values."
        )


def _model_combo_description() -> str:
    """Build model_combo field description from config.json."""
    try:
        cfg = _load_config()
        combos = cfg.get("ui_model_combos", {})
        if not combos:
            return "Model configuration. Default: Azure Foundry."
        names = list(combos.keys())
        default = names[0]
        options = ", ".join(f'"{n}"' for n in names)
        return (
            f"Model configuration. ALWAYS use the default "
            f'"{default}" unless the user explicitly requests a '
            f"different model. Available: {options}."
        )
    except Exception:
        return (
            "Model configuration. ALWAYS use the default "
            '"Azure Foundry" unless the user explicitly requests '
            "a different model."
        )


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
        "MODEL: Always use the default model_combo unless the user "
        "explicitly requests a different one.\n\n"
        "TOOLS:\n"
        "  - search: Find relevant text passages across documents\n"
        "  - get_document: Retrieve full metadata for a specific document\n\n"
        "For synthesised research answers, use the Evidence Lab A2A agent "
        "at <base_url>/a2a (Agent-to-Agent protocol)."
    ),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=True
    ),
    structured_output=True,
)
async def search(
    query: Annotated[
        str,
        Field(
            description=(
                "Natural language search query. Examples: "
                '"impact of climate change on food security", '
                '"gender equality in humanitarian response"'
            )
        ),
    ],
    data_source: Annotated[
        str,
        Field(description=_data_source_description()),
    ] = "uneg",
    limit: Annotated[
        int,
        Field(description="Maximum number of results to return (1-100, default 10)"),
    ] = 10,
    filters: Annotated[
        Optional[Any],
        Field(description=_filters_description()),
    ] = None,
    section_types: Annotated[
        Optional[List[str]],
        Field(
            description=(
                "Restrict to specific document sections. Options: "
                '"executive_summary", "findings", "recommendations", '
                '"conclusions", "methodology", "context", "lessons_learned", "other"'
            )
        ),
    ] = None,
    rerank: Annotated[
        bool,
        Field(
            description=(
                "Rerank results with cross-encoder for better relevance. "
                "Requires Azure Foundry reranker to be configured. "
                "Default false for MCP to avoid dependency."
            )
        ),
    ] = False,
    recency_boost: Annotated[
        bool,
        Field(
            description=("Boost more recently published documents in relevance scoring")
        ),
    ] = False,
    field_boost: Annotated[
        bool, Field(description=("Apply field-specific importance weighting"))
    ] = True,
    model_combo: Annotated[
        str,
        Field(description=(_model_combo_description())),
    ] = "Azure Foundry",
    include_facets: Annotated[
        bool,
        Field(
            description=(
                "If true, return available filter values (facets) alongside "
                "results. Use this on first search to discover what "
                "organizations, years, countries, SDGs, etc. are available "
                "for filtering. Facets include value counts so you can see "
                "which filters are most relevant."
            )
        ),
    ] = False,
) -> MCPSearchResponse:
    """Search evaluation documents using hybrid semantic + keyword search.

    START HERE for raw evidence. Returns text passages so you can read,
    quote, and analyse directly. For synthesised narrative answers, use
    the Evidence Lab A2A agent instead of this tool.

    Returns ranked text passages with metadata including document title,
    organization, year, country, and relevance score. Results are ordered
    by relevance with scores between 0 and 1.

    Each result contains: text (the matching passage), title, organization,
    year, doc_id, chunk_id, score, page_num, headings, and section_type.

    AVAILABLE DATA SOURCES:
    - "uneg": ~15,000 UN evaluation reports from 20+ agencies (1985-2027)
    - "worldbank": World Bank Fraud and Integrity investigation reports
    - "unmandates": ~4,000 UN resolutions and decisions

    FILTER FIELDS (vary by data source):
    For "uneg": organization, published_year, document_type, country,
      language, src_geographic_scope, tag_sdg, tag_cross_cutting_theme
    For "worldbank": organization, published_year, document_type, country,
      region, theme, topic, language, tag_sdg
    For "unmandates": organization, published_year, document_type,
      document_symbol, subject, tag_sdg

    SECTION TYPES: executive_summary, findings, recommendations,
      conclusions, methodology, context, lessons_learned, other

    IMPORTANT — your response MUST include:
    1. Every factual claim MUST have at least one clickable inline citation:
       [[1]](url), [[2]](url). Use the citations array from the response.
    2. A References section (each ref on its OWN line) — copy from the
       references array in the response.
    3. Caveat any totals: semantic search matches variations, so counts
       are approximate.
    """
    from mcp_server.tools.search import mcp_search

    t0 = time.monotonic()
    auth_info: dict = request_auth.get()
    status = "ok"
    error_msg = None
    result = None

    try:
        result = await mcp_search(
            query=query,
            data_source=data_source,
            limit=limit,
            filters=(
                (json.loads(filters) if isinstance(filters, str) else filters)
                if filters
                else None
            ),
            section_types=section_types,
            rerank=rerank,
            recency_boost=recency_boost,
            field_boost=field_boost,
            model_combo=model_combo,
            include_facets=include_facets,
        )
        return result
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        raise
    finally:
        duration_ms = (time.monotonic() - t0) * 1000
        output_summary = (
            result.model_dump_json() if result is not None else f"status={status}"
        )
        log_mcp_call(
            tool_name="search",
            auth_info=auth_info,
            client_ip=request_client_ip.get(),
            input_params={
                "query": query,
                "data_source": data_source,
                "limit": limit,
                "filters": filters,
            },
            output_summary=output_summary,
            duration_ms=duration_ms,
            status=status,
            error_message=error_msg,
        )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    structured_output=True,
)
async def get_document(
    doc_id: Annotated[
        str,
        Field(
            description=(
                "Unique document identifier (returned in search results as doc_id)"
            )
        ),
    ],
    data_source: Annotated[
        str,
        Field(
            description=(
                "Data collection containing the document. Options: "
                '"uneg" (default), "worldbank", "unmandates"'
            )
        ),
    ] = "uneg",
) -> MCPDocumentResponse:
    """Retrieve full metadata and content for a specific document.

    Returns the complete document record including: title, organization,
    publication year, document type, country, language, abstract,
    AI-generated summary, table of contents, and all indexed metadata.

    Use this tool after the search tool to get full details about a
    document found in search results. Pass the doc_id from the search
    result.

    The metadata dict contains all available fields for the document,
    which vary by data source and document.
    """
    from mcp_server.tools.document import mcp_get_document

    t0 = time.monotonic()
    auth_info: dict = request_auth.get()
    status = "ok"
    error_msg = None
    result = None

    try:
        result = await mcp_get_document(doc_id=doc_id, data_source=data_source)
        return result
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        raise
    finally:
        duration_ms = (time.monotonic() - t0) * 1000
        output_summary = (
            result.model_dump_json() if result is not None else f"status={status}"
        )
        log_mcp_call(
            tool_name="get_document",
            auth_info=auth_info,
            client_ip=request_client_ip.get(),
            input_params={"doc_id": doc_id, "data_source": data_source},
            output_summary=output_summary,
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
    from mcp_server.prompts.research import research_question_prompt

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
    from mcp_server.prompts.research import comparative_analysis_prompt

    return comparative_analysis_prompt(topic=topic, dimension=dimension)
