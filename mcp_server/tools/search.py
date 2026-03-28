"""MCP search tool — semantic search over evaluation documents."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from mcp_server.schemas import MCPSearchResponse, MCPSearchResult

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
    model_combo: str = "Azure Foundry",
    include_facets: bool = False,
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
        from pipeline.db import UI_MODEL_COMBOS

        combo = UI_MODEL_COMBOS.get(model_combo, {})
        dense_model = combo.get("embedding_model")
        rerank_model = combo.get("reranker_model") if rerank else None

        db = get_db_for_source(data_source)
        return search_chunks(
            query=query,
            limit=limit,
            db=db,
            data_source=data_source,
            filters=filters,
            rerank=rerank,
            rerank_model=rerank_model,
            recency_boost=recency_boost,
            section_types=section_types,
            dense_model=dense_model,
        )

    raw_results = await loop.run_in_executor(_executor, _run_search)

    # Enrich with Postgres metadata
    results = _convert_results(raw_results, data_source)

    facets = None
    if include_facets:
        facets = await loop.run_in_executor(
            _executor,
            lambda: _fetch_facets(data_source),
        )

    return MCPSearchResponse(
        results=results,
        total=len(results),
        query=query,
        data_source=data_source,
        facets=facets,
    )


def _fetch_facets(data_source: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch available filter values (facets) for a data source.

    Returns a dict mapping field names to lists of {value, count} dicts,
    limited to top 30 values per field for conciseness.
    """
    from pipeline.db import get_default_filter_fields, get_taxonomy_filter_fields
    from ui.backend.utils.app_state import get_db_for_source

    source = data_source or "uneg"
    db = get_db_for_source(source)
    filter_fields = get_default_filter_fields(source)
    taxonomy_fields = get_taxonomy_filter_fields(source)
    filter_fields = {**filter_fields, **taxonomy_fields}

    facets: Dict[str, List[Dict[str, Any]]] = {}
    for field_key, field_label in filter_fields.items():
        if field_key in ("title",):
            continue
        # Core fields are stored with map_ prefix in Qdrant
        qdrant_key = field_key
        if not field_key.startswith(("src_", "tag_")):
            qdrant_key = f"map_{field_key}"
        try:
            raw = db.facet_documents(qdrant_key, limit=30)
        except Exception:
            continue
        if not raw:
            continue
        # Sort by count descending, take top 30
        sorted_items = sorted(raw.items(), key=lambda x: -x[1])[:30]
        facets[field_key] = [
            {"value": str(k), "count": v}
            for k, v in sorted_items
            if k is not None and str(k).strip()
        ]
    return facets


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
