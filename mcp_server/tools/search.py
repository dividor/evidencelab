"""MCP search tool — semantic search over evaluation documents."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from mcp_server.schemas import MCPCitation, MCPSearchResponse, MCPSearchResult

logger = logging.getLogger(__name__)

# Shared executor for running synchronous search in a thread
_executor = ThreadPoolExecutor(max_workers=4)

_CITATION_GUIDANCE = (
    "IMPORTANT: You MUST include ALL of the following in your response:\n"
    "1. Every factual claim MUST have at least one clickable inline citation: "
    "[[1]](url), [[2]](url). Renumber sequentially from 1 in your response order.\n"
    "2. Include a References section (each ref on its OWN line) for every item "
    "you cited.\n"
    "3. Include a 'Browse in Evidence Lab' section with a link to the Evidence Lab "
    "search page so the user can explore results directly.\n"
    "4. When reporting counts from a text/semantic query, caveat that the total "
    "is approximate — semantic search matches variations and related terms.\n"
    "Do NOT omit inline citations. Do NOT put multiple references on one line."
)

# Fields too large for MCP responses — strip from metadata
_EXCLUDE_FROM_META = frozenset(
    {
        "full_summary",
        "abstractive_summary",
        "data",
        "toc",
        "toc_classified",
        "status",
        "status_timestamp",
        "filepath",
        "parsed_folder",
        "stages",
        "error_file",
        "error_checksum",
        "error_message",
        "download_error",
        "file_checksum",
        "metadata_checksum",
    }
)


async def mcp_search(
    query: str,
    data_source: Optional[str] = None,
    limit: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    section_types: Optional[List[str]] = None,
    rerank: bool = True,
    recency_boost: bool = False,
    field_boost: bool = True,
    model_combo: str = "Azure Foundry",
    include_facets: bool = False,
) -> MCPSearchResponse:
    """Run search using the same code path as the API search endpoint."""
    from ui.backend.routes.search import (
        _build_chunk_cache,
        _build_doc_cache,
        _build_search_results,
    )
    from ui.backend.services.search import search_chunks
    from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source

    limit = max(1, min(limit, 100))
    source = data_source or "uneg"
    loop = asyncio.get_running_loop()

    def _run():
        from pipeline.db import UI_MODEL_COMBOS

        combo = UI_MODEL_COMBOS.get(model_combo, {})
        dense_model = combo.get("embedding_model")
        rerank_model = combo.get("reranker_model") if rerank else None

        db = get_db_for_source(source)
        pg = get_pg_for_source(source)

        # Same search as API endpoint
        raw_results = search_chunks(
            query=query,
            limit=limit,
            db=db,
            data_source=source,
            filters=filters,
            rerank=rerank,
            rerank_model=rerank_model,
            recency_boost=recency_boost,
            section_types=section_types,
            dense_model=dense_model,
        )

        # Build caches and results using same functions as API
        doc_cache = _build_doc_cache(pg, raw_results)
        chunk_cache = _build_chunk_cache(pg, raw_results)
        search_results = _build_search_results(
            raw_results,
            doc_cache,
            chunk_cache,
            data_source=source,
            limit=limit,
            min_chunk_size=0,
        )

        return search_results

    search_results = await loop.run_in_executor(_executor, _run)

    # Convert SearchResult objects to MCP schema with citations
    results: List[MCPSearchResult] = []
    citations: List[MCPCitation] = []
    references: List[str] = []
    seen_docs: Dict[str, int] = {}

    for i, sr in enumerate(search_results, 1):
        # Only keep clean user-facing metadata fields
        _KEEP_FIELDS = {
            "country",
            "document_type",
            "language",
            "region",
            "theme",
            "pdf_url",
            "report_url",
            "summary",
            "taxonomies",
        }
        meta = {k: v for k, v in (sr.metadata or {}).items() if k in _KEEP_FIELDS and v}

        # Build citation URL — prefer report_url, fall back to pdf_url
        # Append #page=N if page number is available
        report_url = (sr.metadata or {}).get("report_url", "")
        pdf_url = (sr.metadata or {}).get("pdf_url", "")
        cite_url = report_url or pdf_url or ""
        page = sr.page_num or 0
        if cite_url and page > 0:
            cite_url = f"{cite_url}#page={page}"

        results.append(
            MCPSearchResult(
                chunk_id=sr.chunk_id,
                doc_id=sr.doc_id,
                text=sr.text,
                page_num=sr.page_num or 0,
                headings=sr.headings or [],
                score=float(sr.score),
                title=sr.title or "",
                organization=sr.organization,
                year=sr.year,
                data_source=source,
                section_type=sr.section_type,
                metadata=meta,
            )
        )

        # Build citation (one per unique document)
        if sr.doc_id not in seen_docs:
            cite_num = len(citations) + 1
            seen_docs[sr.doc_id] = cite_num
            org = sr.organization or "Unknown"
            year = sr.year or ""
            title = sr.title or f"Document {cite_num}"
            cite_title = f"{title} ({org}, {year})" if year else f"{title} ({org})"

            citations.append(
                MCPCitation(
                    label=f"[{cite_num}]",
                    url=cite_url,
                    title=cite_title,
                    organization=sr.organization,
                    year=sr.year,
                )
            )
            if cite_url:
                references.append(f"[{cite_num}] [{cite_title}]({cite_url})")
            else:
                references.append(f"[{cite_num}] {cite_title}")

    summary = (
        f"Found {len(results)} results from {len(citations)} documents. "
        f"Use the citations below for attribution."
    )

    facets = None
    if include_facets:
        facets = await loop.run_in_executor(
            _executor,
            lambda: _fetch_facets(source),
        )

    return MCPSearchResponse(
        total=len(results),
        query=query,
        summary=summary,
        results=results,
        citations=citations,
        references=references,
        citation_guidance=_CITATION_GUIDANCE,
        data_source=source,
        facets=facets,
    )


def _fetch_facets(data_source: str) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch available filter values (facets) for a data source."""
    from pipeline.db import get_default_filter_fields, get_taxonomy_filter_fields
    from ui.backend.utils.app_state import get_db_for_source

    db = get_db_for_source(data_source)
    filter_fields = get_default_filter_fields(data_source)
    taxonomy_fields = get_taxonomy_filter_fields(data_source)
    filter_fields = {**filter_fields, **taxonomy_fields}

    facets: Dict[str, List[Dict[str, Any]]] = {}
    for field_key in filter_fields:
        if field_key in ("title",):
            continue
        qdrant_key = field_key
        if not field_key.startswith(("src_", "tag_")):
            qdrant_key = f"map_{field_key}"
        try:
            raw = db.facet_documents(qdrant_key, limit=30)
        except Exception:
            continue
        if not raw:
            continue
        sorted_items = sorted(raw.items(), key=lambda x: -x[1])[:30]
        facets[field_key] = [
            {"value": str(k), "count": v}
            for k, v in sorted_items
            if k is not None and str(k).strip()
        ]
    return facets
