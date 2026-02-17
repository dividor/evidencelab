import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from qdrant_client.http import models as qmodels

from pipeline.db import get_field_mapping, get_filter_fields, get_taxonomy_filter_fields
from pipeline.utilities.text_cleaning import clean_text
from ui.backend.routes.highlight import infer_paragraphs_from_bboxes
from ui.backend.schemas import Facets, FacetValue, SearchResponse, SearchResult
from ui.backend.services.search import (
    get_search_facets,
    scroll_filtered_chunks,
    search_chunks,
    search_facet_values,
    search_titles,
)
from ui.backend.services.search_models import apply_field_boost
from ui.backend.utils.app_limits import get_rate_limits, limiter
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source, logger
from ui.backend.utils.document_utils import (
    map_core_field_to_storage,
    normalize_document_payload,
)
from ui.backend.utils.facet_helpers import build_facets_from_db
from ui.backend.utils.language_codes import LANGUAGE_CODES

RATE_LIMIT_SEARCH, RATE_LIMIT_DEFAULT, RATE_LIMIT_AI = get_rate_limits()
MAX_CONCURRENT_SEARCHES = int(os.environ.get("MAX_CONCURRENT_SEARCHES", "2"))
search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)
router = APIRouter()


def _normalize_language_filter(language: Optional[str]) -> Optional[str]:
    """Convert full language name(s) back to codes for DB queries."""
    if not language:
        return None
    parts = [v.strip() for v in language.split(",") if v.strip()]
    mapped = [LANGUAGE_CODES.get(p, p) for p in parts]
    return ",".join(mapped)


def _build_core_filters(
    organization: Optional[str],
    title: Optional[str],
    published_year: Optional[str],
    document_type: Optional[str],
    country: Optional[str],
    language: Optional[str],
) -> Dict[str, Any]:
    return {
        k: v
        for k, v in {
            "organization": organization,
            "title": title,
            "published_year": published_year,
            "document_type": document_type,
            "country": country,
            "language": _normalize_language_filter(language),
        }.items()
        if v is not None
    }


def _parse_section_types(section_types: Optional[str]) -> Optional[List[str]]:
    if not section_types:
        return None
    items = [s.strip() for s in section_types.split(",") if s.strip()]
    return items or None


async def _run_search_chunks(
    query: str,
    *,
    limit: int,
    dense_weight: Optional[float],
    db,
    filters: Optional[Dict[str, Any]],
    rerank: bool,
    recency_boost: bool,
    recency_weight: float,
    recency_scale_days: int,
    section_types: Optional[List[str]],
    keyword_boost_short_queries: bool,
    min_chunk_size: int,
    dense_model: Optional[str],
    rerank_model: Optional[str],
    max_rerank_candidates: int = 0,
):
    t0 = time.time()
    async with search_semaphore:
        results = await run_in_threadpool(
            search_chunks,
            query,
            limit=limit,
            dense_weight=dense_weight,
            db=db,
            filters=filters if filters else None,
            rerank=rerank,
            recency_boost=recency_boost,
            recency_weight=recency_weight,
            recency_scale_days=recency_scale_days,
            section_types=section_types,
            keyword_boost_short_queries=keyword_boost_short_queries,
            min_chunk_size=min_chunk_size,
            dense_model=dense_model,
            rerank_model=rerank_model,
            max_rerank_candidates=max_rerank_candidates,
        )
    t1 = time.time()
    logger.info(
        "[TIMING] search_chunks: %.3fs (section_types=%s)",
        t1 - t0,
        section_types,
    )
    return results


def _build_doc_cache(pg, results) -> Dict[str, Any]:
    doc_ids = list(
        set(
            str(result.payload.get("doc_id") or result.payload.get("sys_doc_id"))
            for result in results
            if result.payload.get("doc_id") or result.payload.get("sys_doc_id")
        )
    )
    if not doc_ids:
        return {}
    return pg.fetch_docs(doc_ids)


def _build_chunk_cache(pg, results) -> Dict[str, Any]:
    chunk_ids = list({str(result.id) for result in results if result.id is not None})
    if not chunk_ids:
        return {}
    return pg.fetch_chunks(chunk_ids)


def _normalize_heading_items(raw_items: Any) -> List[str]:
    if raw_items is None:
        return []
    if isinstance(raw_items, str):
        return [raw_items]
    if isinstance(raw_items, list):
        items: List[str] = []
        for item in raw_items:
            if isinstance(item, dict):
                text = (
                    item.get("text")
                    or item.get("title")
                    or item.get("heading")
                    or item.get("name")
                )
                if text:
                    items.append(str(text))
            else:
                items.append(str(item))
        return items
    return [str(raw_items)]


def _build_heading_candidates(chunk_payload: Dict[str, Any]) -> List[str]:
    candidates = []
    items = _normalize_heading_items(chunk_payload.get("sys_headings"))
    if items:
        candidates.append(" > ".join([item for item in items if item]))
    return [candidate for candidate in candidates if candidate]


def _strip_heading_row(text: str, chunk_payload: Dict[str, Any]) -> str:
    if not text:
        return text
    lines = text.splitlines()
    first_line_index = None
    for i, line in enumerate(lines):
        if line.strip():
            first_line_index = i
            break
    if first_line_index is None:
        return text
    first_line = lines[first_line_index]
    normalized_line = first_line.strip().strip("-").strip()
    candidates = _build_heading_candidates(chunk_payload)
    normalized_line_lower = normalized_line.lower()
    matches_heading = any(
        normalized_line_lower == candidate.lower() for candidate in candidates
    )
    if not matches_heading:
        raw_line = first_line.strip()
        if raw_line.startswith("--") and raw_line.endswith("--") and " > " in raw_line:
            matches_heading = True
    if not matches_heading:
        return text
    lines.pop(first_line_index)
    if first_line_index < len(lines) and not lines[first_line_index].strip():
        lines.pop(first_line_index)
    return "\n".join(lines).lstrip("\n")


def _deduplicate_results(results: List[SearchResult]) -> List[SearchResult]:
    """
    Remove results with identical text across different documents.
    When duplicates are found, keep the one from the most recently published
    document (highest year). Ties broken by higher search score.
    """
    if not results:
        return results

    seen: dict[str, SearchResult] = {}
    for result in results:
        key = result.text.strip()
        existing = seen.get(key)
        if existing is None:
            seen[key] = result
        else:
            existing_year = int(existing.year or "0")
            result_year = int(result.year or "0")
            if result_year > existing_year or (
                result_year == existing_year and result.score > existing.score
            ):
                seen[key] = result

    deduped = list(seen.values())
    removed = len(results) - len(deduped)
    if removed > 0:
        logger.info(
            "[DEDUPLICATE] Removed %d duplicate results (%d -> %d)",
            removed,
            len(results),
            len(deduped),
        )
    return deduped


def _apply_auto_min_score_filter(results: List[SearchResult]) -> List[SearchResult]:
    """
    Filter results by calculating 30th percentile threshold.
    Results below this threshold are filtered out.
    """
    if not results:
        return results

    scores = [r.score for r in results if r.score is not None]
    if not scores:
        return results

    # Calculate 30th percentile
    sorted_scores = sorted(scores)
    percentile_index = int(len(sorted_scores) * 0.3)
    if percentile_index >= len(sorted_scores):
        percentile_index = len(sorted_scores) - 1
    threshold = sorted_scores[percentile_index]

    # Filter results
    filtered = [r for r in results if r.score is not None and r.score >= threshold]
    logger.info(
        "[AUTO_MIN_SCORE] 30th percentile threshold: %.6f, filtered %d/%d results",
        threshold,
        len(results) - len(filtered),
        len(results),
    )
    return filtered


def _build_search_results(
    results,
    doc_cache,
    chunk_cache,
    data_source: Optional[str],
    limit: int,
    min_chunk_size: int,
):
    filtered_results = []
    for result in results:
        doc_id_raw = result.payload.get("doc_id") or result.payload.get("sys_doc_id")
        doc_id = str(doc_id_raw) if doc_id_raw is not None else None
        if doc_id not in doc_cache:
            continue
        doc = doc_cache[doc_id]
        normalized_doc = normalize_document_payload(doc)

        chunk_payload = chunk_cache.get(str(result.id), {})
        chunk_text = clean_text(
            chunk_payload.get("sys_text") or result.payload.get("sys_text", "")
        )
        chunk_bboxes = chunk_payload.get("sys_bbox", [])
        formatted_text = infer_paragraphs_from_bboxes(
            chunk_text.replace("\n", "\n\n"), chunk_bboxes
        )
        display_text = _strip_heading_row(formatted_text, chunk_payload)
        if min_chunk_size > 0 and len(clean_text(display_text)) < min_chunk_size:
            continue

        filtered_results.append(
            SearchResult(
                id=str(result.id),
                chunk_id=str(result.id),
                doc_id=doc_id,
                document_title=clean_text(normalized_doc.get("title", "Unknown")),
                data_source=doc.get("data_source", data_source),
                text=display_text,
                page_num=(
                    chunk_payload.get("sys_page_num")
                    if chunk_payload.get("sys_page_num") is not None
                    else 0
                ),
                chunk_elements=chunk_payload.get("sys_chunk_elements"),
                headings=chunk_payload.get("sys_headings") or [],
                section_type=(
                    chunk_payload.get("tag_section_type")
                    or result.payload.get("tag_section_type")
                ),
                score=result.score,
                item_types=chunk_payload.get("sys_item_types"),
                bbox=chunk_bboxes,
                elements=chunk_payload.get("sys_elements"),
                table_data=chunk_payload.get("sys_table_data"),
                tables=chunk_payload.get("sys_tables"),
                images=chunk_payload.get("sys_images"),
                title=clean_text(normalized_doc.get("title", "Unknown")),
                organization=normalized_doc.get("organization"),
                year=(
                    str(normalized_doc.get("published_year"))
                    if normalized_doc.get("published_year") is not None
                    else None
                ),
                metadata={
                    k: v for k, v in doc.items() if k not in ("abstractive_summary",)
                },
            )
        )

        if len(filtered_results) >= limit:
            break

    return filtered_results


def _build_needed_fields(
    filter_fields_config: Dict[str, str], data_source: Optional[str]
) -> List[str]:
    needed_fields = [
        _resolve_storage_field(core_field, data_source)
        for core_field in filter_fields_config.keys()
        if core_field != "title"
    ]
    return list(set(needed_fields))


def _resolve_storage_field(core_field: str, data_source: Optional[str]) -> str:
    if core_field != "language":
        return map_core_field_to_storage(core_field)
    source = data_source or "uneg"
    field_mapping = get_field_mapping(source)
    if field_mapping.get("language") == "sys_language":
        return "sys_language"
    return map_core_field_to_storage(core_field)


def _build_core_filters_from_params(
    organization: Optional[str],
    title: Optional[str],
    published_year: Optional[str],
    document_type: Optional[str],
    country: Optional[str],
    language: Optional[str],
) -> Dict[str, Any]:
    return {
        "organization": organization,
        "title": title,
        "published_year": published_year,
        "document_type": document_type,
        "country": country,
        "language": _normalize_language_filter(language),
    }


def _split_filter_values(value: Any) -> Optional[List[str]]:
    if isinstance(value, str) and "," in value:
        values = [item.strip() for item in value.split(",") if item.strip()]
        if values:
            return values
    return None


def _build_facet_filter(core_filters: Dict[str, Any], data_source: Optional[str]):
    facet_conditions = []
    for core_field, value in core_filters.items():
        if not value:
            continue
        storage_field = _resolve_storage_field(core_field, data_source)
        if core_field == "published_year":
            value = str(value)
        multi_values = _split_filter_values(value)
        facet_conditions.append(
            qmodels.FieldCondition(
                key=storage_field,
                match=(
                    qmodels.MatchAny(any=multi_values)
                    if multi_values
                    else qmodels.MatchValue(value=value)
                ),
            )
        )
    return qmodels.Filter(must=facet_conditions) if facet_conditions else None


@router.get("/search/titles")
@limiter.limit(RATE_LIMIT_SEARCH)
async def perform_title_search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = 50,
    dense_weight: float = None,
    data_source: str = Query("uneg", description="Data source to search"),
    model: Optional[str] = Query(None, description="Embedding model to use"),
    # Accept filter params dynamically
    organization: Optional[str] = Query(None),
    published_year: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
):
    """
    Search specifically for document titles using hybrid search.
    Returns matching document metadata.
    """
    filters = {
        "organization": organization,
        "published_year": published_year,
        "country": country,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}

    try:
        # Get DB for source
        db = get_db_for_source(data_source)

        # Perform search using shared logic
        results = search_titles(
            query=q,
            limit=limit,
            dense_weight=dense_weight,
            db=db,
            filters=filters,
            dense_model=model,
        )

        # Format results
        response_data = []
        for hit in results:
            normalized_payload = normalize_document_payload(hit.payload or {})
            response_data.append(
                {
                    "doc_id": hit.payload.get("doc_id"),
                    "title": normalized_payload.get("title"),
                    "organization": normalized_payload.get("organization"),
                    "year": normalized_payload.get("published_year"),
                    "score": hit.score,
                }
            )

        return response_data

    except Exception as e:
        logger.error(f"Title Search failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _handle_title_filter(
    pg, core_filters: Dict[str, Any], q: str
) -> Optional[SearchResponse]:
    title_filter = core_filters.get("title")
    if not title_filter:
        return None

    t_title_filter_start = time.time()
    title_doc_ids = pg.fetch_doc_ids_by_title(title_filter)
    t_title_filter_end = time.time()
    logger.info(
        "[TIMING] title_doc_id_fetch: %.3fs (%s matches)",
        t_title_filter_end - t_title_filter_start,
        len(title_doc_ids),
    )
    if not title_doc_ids:
        return SearchResponse(
            results=[],
            total=0,
            query=q,
            filters={"title": [title_filter]},
        )
    core_filters.pop("title", None)
    core_filters["doc_id"] = title_doc_ids
    return None


def _build_filters_response(
    core_filters: Dict[str, Any], title_filter: Optional[str]
) -> Dict[str, List[str]]:
    filters_response: Dict[str, List[str]] = {}
    for key, value in core_filters.items():
        if value is None:
            filters_response[key] = []
        elif isinstance(value, list):
            filters_response[key] = [str(item) for item in value]
        else:
            filters_response[key] = [value]
    if title_filter:
        filters_response["title"] = [title_filter]
    return filters_response


def _parse_boost_fields(raw: Optional[str]) -> Dict[str, float]:
    """Parse 'country:0.5,organization:0.3' into {field: weight}."""
    if not raw:
        return {}
    config: Dict[str, float] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            name, wstr = item.split(":", 1)
            try:
                config[name.strip()] = float(wstr)
            except ValueError:
                config[name.strip()] = 0.5
        else:
            config[item] = 0.5
    return config


def _add_taxonomy_filters(core_filters: Dict, query_params) -> None:
    """Pick up tag_* query params (taxonomy filters) dynamically."""
    for name, value in query_params.items():
        if name.startswith("tag_") and value:
            core_filters[name] = value


def _fetch_and_build_results(pg, results, data_source, limit, min_chunk_size):
    """Build doc/chunk caches and construct SearchResult list. Returns None if no docs."""
    t_doc = time.time()
    doc_cache = _build_doc_cache(pg, results)
    logger.info(
        "[TIMING] doc_cache_fetch: %.3fs (%s docs)", time.time() - t_doc, len(doc_cache)
    )
    if not doc_cache:
        return None
    t_chunk = time.time()
    chunk_cache = _build_chunk_cache(pg, results)
    logger.info(
        "[TIMING] chunk_cache_fetch: %.3fs (%s chunks)",
        time.time() - t_chunk,
        len(chunk_cache),
    )
    t_build = time.time()
    built = _build_search_results(
        results, doc_cache, chunk_cache, data_source, limit, min_chunk_size
    )
    logger.info(
        "[TIMING] build_results: %.3fs (%s results)", time.time() - t_build, len(built)
    )
    return built


def _apply_post_retrieval_boosts(
    results: List,
    query: str,
    field_boost: bool,
    field_boost_fields: Optional[str],
    auto_min_score: bool,
    deduplicate: bool,
    db,
    source: Optional[str],
) -> List:
    """Apply field boost, auto min score, and deduplication."""
    boost_cfg = (
        _parse_boost_fields(field_boost_fields) if field_boost and query.strip() else {}
    )
    if boost_cfg:
        known = _gather_known_values(db, boost_cfg, source)
        results = apply_field_boost(results, query, boost_cfg, known)
    if auto_min_score:
        results = _apply_auto_min_score_filter(results)
    if deduplicate:
        results = _deduplicate_results(results)
    return results


def _split_facet_values(raw_counts) -> List[str]:
    """Expand raw facet counts into individual values, splitting comma-separated entries."""
    values: set = set()
    for rv in raw_counts:
        if rv is None or rv == "":
            continue
        s = str(rv)
        parts = [p.strip() for p in s.split(",")] if "," in s else [s]
        values.update(p for p in parts if p)
    return list(values)


def _gather_known_values(
    db, boost_fields: Dict[str, float], source: Optional[str]
) -> Dict[str, List[str]]:
    """Fetch known facet values for each boost field from the DB."""
    known: Dict[str, List[str]] = {}
    for core_field in boost_fields:
        storage_field = _resolve_storage_field(core_field, source)
        raw_counts = db.facet_documents(
            key=storage_field,
            filter_conditions=None,
            limit=2000,
            exact=False,
        )
        known[core_field] = _split_facet_values(raw_counts)
    return known


@router.get("/search", response_model=SearchResponse)
@limiter.limit(RATE_LIMIT_SEARCH)
async def search(
    request: Request,
    q: str = Query("", description="Search query (empty for filter-only counting)"),
    limit: int = Query(50, description="Maximum results"),
    # Core field names (mapped to source fields internally)
    organization: Optional[str] = Query(None, description="Filter by organization"),
    title: Optional[str] = Query(None, description="Filter by title (partial match)"),
    published_year: Optional[str] = Query(None, description="Filter by published year"),
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    country: Optional[str] = Query(None, description="Filter by country"),
    language: Optional[str] = Query(None, description="Filter by language"),
    dense_weight: Optional[float] = Query(
        None, ge=0.0, le=1.0, description="Dense search weight (0=keyword, 1=semantic)"
    ),
    rerank: bool = Query(False, description="Enable cross-encoder reranking"),
    # Recency boost parameters
    recency_boost: bool = Query(
        False, description="Enable recency boosting based on publication date"
    ),
    recency_weight: float = Query(
        0.15, ge=0.0, le=1.0, description="Weight for recency (0=none, 1=max)"
    ),
    recency_scale_days: int = Query(
        365, ge=30, le=3650, description="Decay scale in days (default 365 = 1 year)"
    ),
    # Content settings
    section_types: Optional[str] = Query(
        None,
        description="Comma-separated section types to filter by (e.g., 'findings,recommendations')",
    ),
    keyword_boost_short_queries: bool = Query(
        True, description="Automatically use keyword boost for short queries (≤2 words)"
    ),
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
    min_chunk_size: int = Query(
        0, description="Minimum character length for chunks (default 0 = no filter)"
    ),
    model: Optional[str] = Query(
        None, description="Name of dense embedding model to use"
    ),
    rerank_model: Optional[str] = Query(
        None, description="Name of reranker model to use"
    ),
    rerank_model_page_size: Optional[int] = Query(
        None, description="Max candidates to send to reranker (0 or None = all)"
    ),
    auto_min_score: bool = Query(
        False, description="Automatically filter bottom 30% of results by score"
    ),
    deduplicate: bool = Query(
        True,
        description="Deduplicate results with identical text "
        "across documents, keeping the most recently published",
    ),
    field_boost: bool = Query(
        True,
        description="Boost results matching field values "
        "(e.g. country, organization) mentioned in the query",
    ),
    field_boost_fields: Optional[str] = Query(
        None,
        description="Comma-separated core field names to boost (e.g. 'country,organization'). "
        "Each field gets a 0.5 weight multiplier.",
    ),
):
    """
    Perform semantic search over document chunks.
    Returns chunks with document metadata joined.
    Optionally accepts dense_weight to control hybrid search balance.
    Filter parameters use core field names which are mapped to source fields.
    """

    t_start = time.time()
    source = data_source if isinstance(data_source, str) and data_source else "uneg"
    db = get_db_for_source(source)
    pg = get_pg_for_source(source)

    try:
        core_filters = _build_core_filters(
            organization,
            title,
            published_year,
            document_type,
            country,
            language,
        )
        _add_taxonomy_filters(core_filters, request.query_params)

        title_filter = core_filters.get("title")
        early_response = _handle_title_filter(pg, core_filters, q)
        if early_response:
            return early_response

        section_types_list = _parse_section_types(section_types)

        if not q.strip():
            # Empty query: scroll with filters only (no embedding needed)
            results = await run_in_threadpool(
                scroll_filtered_chunks,
                filters=core_filters or None,
                limit=limit,
                data_source=source,
                section_types=section_types_list,
            )
        else:
            results = await _run_search_chunks(
                q,
                limit=limit,
                dense_weight=dense_weight,
                db=db,
                filters=core_filters or None,
                rerank=rerank,
                recency_boost=recency_boost,
                recency_weight=recency_weight,
                recency_scale_days=recency_scale_days,
                section_types=section_types_list,
                keyword_boost_short_queries=keyword_boost_short_queries,
                min_chunk_size=min_chunk_size,
                dense_model=model,
                rerank_model=rerank_model,
                max_rerank_candidates=rerank_model_page_size or 0,
            )

        t2 = time.time()
        filtered_results = _fetch_and_build_results(
            pg, results, data_source, limit, min_chunk_size
        )
        if filtered_results is None:
            return SearchResponse(results=[], total=0, query=q, filters={})

        filtered_results = _apply_post_retrieval_boosts(
            filtered_results,
            q,
            field_boost,
            field_boost_fields,
            auto_min_score,
            deduplicate,
            db,
            source,
        )

        t3 = time.time()
        logger.info("[TIMING] post_build: %.3fs", t3 - t2)
        logger.info("[TIMING] TOTAL /search: %.3fs", t3 - t_start)

        filters_response = _build_filters_response(core_filters, title_filter)
        return SearchResponse(
            results=filtered_results,
            total=len(filtered_results),
            query=q,
            filters=filters_response,
        )

    except Exception as e:
        logger.exception("Search error", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _get_indexed_doc_ids(pg, source: str) -> List[str]:
    """Fetch indexed document IDs from Postgres."""
    return pg.fetch_indexed_doc_ids()


def _build_metadata_filter_condition(
    core_field: str, value: Any, storage_field: str
) -> qmodels.Filter:
    """Build a Qdrant filter condition for a single metadata field."""
    if core_field == "title":
        return qmodels.Filter(
            should=[
                qmodels.FieldCondition(
                    key=storage_field, match=qmodels.MatchText(text=value)
                )
            ]
        )
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key=storage_field, match=qmodels.MatchValue(value=value)
            )
        ]
    )


def _build_docsearch_filters(
    q: str, core_filters: Dict[str, Any], indexed_doc_ids: List[str], db
) -> Optional[qmodels.Filter]:
    """Build combined Qdrant filter conditions for document search."""
    filter_conditions = []

    if q.strip():
        search_conditions = db._search_conditions(q.strip())
        if search_conditions:
            filter_conditions.append(qmodels.Filter(should=search_conditions))

    for core_field, value in core_filters.items():
        if not value:
            continue
        storage_field = map_core_field_to_storage(core_field)
        if not storage_field:
            continue
        filter_conditions.append(
            _build_metadata_filter_condition(core_field, value, storage_field)
        )

    filter_conditions.append(
        qmodels.Filter(should=[qmodels.HasIdCondition(has_id=indexed_doc_ids)])
    )

    return qmodels.Filter(must=filter_conditions) if filter_conditions else None


def _format_document_result(
    point, sys_fields_map: Dict[str, Any], source: str
) -> Optional[SearchResult]:
    """Format a single document point into a SearchResult."""
    if not point.payload:
        return None

    doc_data = {"doc_id": str(point.id), **point.payload}
    sys_fields = sys_fields_map.get(str(point.id), {})
    doc_data.update(sys_fields)
    normalized_doc = normalize_document_payload(doc_data)

    full_summary = normalized_doc.get("sys_full_summary", "")
    return SearchResult(
        chunk_id=str(point.id),
        doc_id=str(point.id),
        text=(
            full_summary[:500] if full_summary else ""
        ),  # Truncated for backwards compatibility
        page_num=1,
        headings=[],
        score=0.0,
        title=normalized_doc.get("title", ""),
        organization=normalized_doc.get("organization"),
        year=normalized_doc.get("published_year"),
        pdf_url=normalized_doc.get("pdf_url"),
        report_url=normalized_doc.get("report_url"),
        metadata=normalized_doc.get("metadata", {}),
        sys_parsed_folder=normalized_doc.get("sys_parsed_folder"),
        sys_filepath=normalized_doc.get("sys_filepath"),
        sys_full_summary=full_summary,  # Full summary without truncation
        data_source=source,
    )


@router.get("/docsearch", response_model=SearchResponse)
@limiter.limit(RATE_LIMIT_SEARCH)
async def docsearch(
    request: Request,
    q: str = Query(
        "",
        description="Search query for document title/summary (empty for filter-only)",
    ),
    limit: int = Query(50, description="Maximum results"),
    # Core field names (mapped to source fields internally)
    organization: Optional[str] = Query(None, description="Filter by organization"),
    title: Optional[str] = Query(None, description="Filter by title (partial match)"),
    published_year: Optional[str] = Query(None, description="Filter by published year"),
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    country: Optional[str] = Query(None, description="Filter by country"),
    language: Optional[str] = Query(None, description="Filter by language"),
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """
    Perform document-level search (searches title and summary, not chunks).
    Returns documents matching the query and filters.
    Used by heatmap when no query is specified and rows are not 'queries'.
    """
    t_start = time.time()
    source = data_source if isinstance(data_source, str) and data_source else "uneg"
    db = get_db_for_source(source)
    pg = get_pg_for_source(source)

    try:
        indexed_doc_ids = _get_indexed_doc_ids(pg, source)
        if not indexed_doc_ids:
            return SearchResponse(results=[], total=0, query=q, filters={}, facets=None)

        core_filters = _build_core_filters(
            organization, title, published_year, document_type, country, language
        )
        for param_name, param_value in request.query_params.items():
            if param_name.startswith("tag_") and param_value:
                core_filters[param_name] = param_value

        combined_filter = _build_docsearch_filters(q, core_filters, indexed_doc_ids, db)

        results = await run_in_threadpool(
            db._scroll_documents, query_filter=combined_filter, end_idx=limit
        )

        doc_ids = [str(point.id) for point in results[:limit] if point.id]
        sys_fields_map = pg.fetch_docs(doc_ids) if doc_ids else {}

        documents = [
            result
            for point in results[:limit]
            if (result := _format_document_result(point, sys_fields_map, source))
            is not None
        ]

        t_end = time.time()
        logger.info(
            "[TIMING] TOTAL /docsearch: %.3fs (%d docs)",
            t_end - t_start,
            len(documents),
        )

        filters_response = _build_filters_response(
            core_filters, core_filters.get("title")
        )
        return SearchResponse(
            results=documents, total=len(documents), query=q, filters=filters_response
        )

    except Exception as e:
        logger.exception("Document search error", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/facet-values")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def search_facet_values_endpoint(
    request: Request,
    field: str = Query(..., description="Field to search for (e.g., 'organization')"),
    q: str = Query(..., description="Search query for values"),
    limit: int = Query(100, description="Max documents to scan"),
    data_source: Optional[str] = Query(None, description="Data source"),
    dense_weight: Optional[float] = Query(None, description="Dense search weight"),
):
    """
    Search for unique values of a specific field (e.g. organization) matching a query.
    Used for server-side filtering in the facet UI.
    """
    try:
        source = data_source or "uneg"

        # Use simple dense search (or native Facet API) to find values
        results = search_facet_values(
            field=field,
            query=q,
            limit=limit,
            dense_weight=dense_weight,
            data_source=source,
        )
        return results
    except Exception as e:
        logger.error(f"Facet search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/facets", response_model=Facets)
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_facets(
    request: Request,
    organization: str = None,
    title: str = None,
    published_year: str = None,
    document_type: str = None,
    country: str = None,
    language: str = None,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
    q: Optional[str] = Query(
        None, description="Search query to filter facets by search results"
    ),
):
    """
    Get facet counts for all filterable fields.
    Used to populate filter UI.
    Includes all documents (not just indexed ones) to match the Documents table view.
    Accepts filter parameters (core field names) to return facets based on current selections.
    """
    try:
        source = data_source or "uneg"
        db = get_db_for_source(source)
        pg = get_pg_for_source(source)
        filter_fields_config = get_filter_fields(source)
        taxonomy_fields = get_taxonomy_filter_fields(source)
        filter_fields_config = {**filter_fields_config, **taxonomy_fields}

        core_filters = _build_core_filters_from_params(
            organization,
            title,
            published_year,
            document_type,
            country,
            language,
        )
        title_filter = core_filters.get("title")
        if title_filter and q:
            title_doc_ids = pg.fetch_doc_ids_by_title(title_filter)
            if not title_doc_ids:
                return Facets(
                    facets={},
                    filter_fields=filter_fields_config,
                )
            core_filters.pop("title", None)
            core_filters["doc_id"] = title_doc_ids

        if q:
            facets_data_raw = get_search_facets(
                query=q,
                filters=core_filters,
                data_source=source,
            )
            facets_data = {
                field: [
                    FacetValue(value=str(item["value"]), count=item["count"])
                    for item in values
                ]
                for field, values in facets_data_raw.items()
            }
            return Facets(facets=facets_data, filter_fields=filter_fields_config)

        _build_needed_fields(filter_fields_config, source)
        facet_filter = _build_facet_filter(core_filters, source)
        facets_result = build_facets_from_db(
            db, filter_fields_config, facet_filter, _resolve_storage_field, pg=pg
        )
        return Facets(facets=facets_result, filter_fields=filter_fields_config)

    except Exception as e:
        logger.error(f"Facets error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
