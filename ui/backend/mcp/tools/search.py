"""MCP search tool — semantic search over evaluation documents."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from ui.backend.mcp.schemas import MCPSearchResponse, MCPSearchResult

logger = logging.getLogger(__name__)

# Shared executor for running synchronous search in a thread
_executor = ThreadPoolExecutor(max_workers=4)


async def mcp_search(
    query: str,
    data_source: Optional[str] = None,
    limit: int = 20,
    filters: Optional[Dict[str, Any]] = None,
    section_types: Optional[List[str]] = None,
    rerank: bool = True,
    recency_boost: bool = False,
    field_boost: bool = True,
) -> MCPSearchResponse:
    """Search evaluation documents using hybrid semantic + keyword search.

    Performs a vector search over chunked documents from UN agencies,
    World Bank, and other development organizations.  Returns ranked
    text passages with metadata.

    Args:
        query: Natural language search query.
        data_source: Data collection to search (e.g. "uneg", "worldbank").
            Defaults to the server's primary collection.
        limit: Maximum number of results to return (1-100, default 20).
        filters: Field filters as ``{field_name: value}`` pairs.  Supported
            fields depend on the data source (e.g. organization,
            published_year, country, language, document_type).
        section_types: Restrict results to specific section types such as
            ``["findings", "recommendations", "lessons_learned"]``.
        rerank: Whether to rerank results with a cross-encoder (default True).
        recency_boost: Boost more recently published documents.
        field_boost: Apply field-specific boosting heuristics.

    Returns:
        MCPSearchResponse with ranked search results.
    """
    from ui.backend.services.search import search_chunks
    from ui.backend.utils.app_state import get_db_for_source

    limit = max(1, min(limit, 100))

    # search_chunks is synchronous — run in executor
    loop = asyncio.get_running_loop()

    def _run_search():
        db = get_db_for_source(data_source)
        return search_chunks(
            query=query,
            limit=limit,
            db=db,
            data_source=data_source,
            filters=filters,
            rerank=rerank,
            recency_boost=recency_boost,
            section_types=section_types,
        )

    raw_results = await loop.run_in_executor(_executor, _run_search)

    # Enrich with Postgres metadata
    results = _convert_results(raw_results, data_source)

    return MCPSearchResponse(
        results=results,
        total=len(results),
        query=query,
        data_source=data_source,
    )


def _convert_results(
    raw_results: list,
    data_source: Optional[str],
) -> List[MCPSearchResult]:
    """Convert Qdrant ScoredPoint objects to MCP search result models."""
    from ui.backend.utils.app_state import get_pg_for_source

    if not raw_results:
        return []

    # Batch-fetch document metadata from Postgres
    doc_ids = list(
        {
            r.payload.get("doc_id") or r.payload.get("sys_doc_id", "")
            for r in raw_results
        }
    )
    doc_ids = [d for d in doc_ids if d]

    doc_meta: Dict[str, Dict[str, Any]] = {}
    try:
        pg = get_pg_for_source(data_source)
        doc_meta = pg.fetch_docs(doc_ids)
    except Exception:
        logger.warning("Failed to fetch doc metadata from Postgres", exc_info=True)

    results: List[MCPSearchResult] = []
    for r in raw_results:
        payload = r.payload or {}
        doc_id = payload.get("doc_id") or payload.get("sys_doc_id", "")
        meta = doc_meta.get(str(doc_id), {})

        # Build metadata dict from all map_* and sys_* fields
        extra_meta: Dict[str, Any] = {}
        for key, value in meta.items():
            if key.startswith("map_") or key.startswith("sys_"):
                clean_key = key.replace("map_", "").replace("sys_", "")
                extra_meta[clean_key] = value

        results.append(
            MCPSearchResult(
                chunk_id=str(r.id),
                doc_id=str(doc_id),
                text=payload.get("sys_text", meta.get("sys_text", "")),
                page_num=payload.get("sys_page_num", 0),
                headings=payload.get("sys_headings", []),
                score=float(r.score),
                title=meta.get("map_title", payload.get("map_title", "")),
                organization=meta.get("map_organization"),
                year=meta.get("map_published_year"),
                data_source=data_source,
                section_type=payload.get("tag_section_type"),
                metadata=extra_meta,
            )
        )

    return results
