"""Reference searches for one heatmap cell."""

from dataclasses import dataclass
from typing import Any

from fastapi.concurrency import run_in_threadpool

from pipeline.db import UI_MODEL_COMBOS, get_default_model_combo
from ui.backend.routes.search import (
    DOCSEARCH_DEFAULT_LIMIT,
    _format_document_result,
    _resolve_chunk_search_filters,
    _run_search_chunks,
    find_document_points,
    prepare_chunk_results,
)
from ui.backend.schemas import SearchResult
from ui.backend.services.heatmap_axes import facet_selection
from ui.backend.services.search_defaults import (
    SYSTEM_SEARCH_DEFAULTS,
    default_section_types,
)
from ui.backend.utils.app_limits import get_search_max_limit
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source
from ui.backend.utils.filter_helpers import normalize_language_filter

QUERY_CELL_LIMIT = min(1000, get_search_max_limit())


@dataclass(frozen=True, slots=True)
class HeatmapHit:
    """Only the fields needed for counting and building a document list."""

    hit_id: str
    doc_id: str
    score: float = 0
    title: str = ""
    year: str | None = None
    organization: str | None = None
    report_url: str | None = None
    pdf_url: str | None = None

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.title, self.year or "", self.organization or "")


@dataclass(frozen=True)
class CellSearch:
    query: str
    filters: dict[str, str | list[str]]


@dataclass
class CellHits:
    hits: list[HeatmapHit]
    capped: bool
    # For attribute cells, defer document formatting to the requested detail page.
    points: list[Any] | None = None


def core_filters(cell: CellSearch) -> dict[str, Any]:
    filters: dict[str, Any] = {
        field: facet_selection(selection) for field, selection in cell.filters.items()
    }
    if "language" in filters:
        filters["language"] = normalize_language_filter(",".join(filters["language"]))
    return filters


def hit_from_result(result: SearchResult) -> HeatmapHit:
    return HeatmapHit(
        hit_id=result.chunk_id,
        doc_id=result.doc_id,
        score=result.score,
        title=result.title,
        year=result.year or result.metadata.get("year"),
        organization=result.organization or result.metadata.get("organization"),
        report_url=result.report_url or result.metadata.get("report_url"),
        pdf_url=result.pdf_url or result.metadata.get("pdf_url"),
    )


def document_hits(source: str, cell: CellSearch, details: bool) -> CellHits:
    db, pg = get_db_for_source(source), get_pg_for_source(source)
    points, _, _ = find_document_points(
        q="",
        limit=DOCSEARCH_DEFAULT_LIMIT,
        core_filters=core_filters(cell),
        source=source,
        db=db,
        pg=pg,
    )
    documents = [point for point in points if point.payload]
    hits = [
        HeatmapHit(hit_id=str(point.id), doc_id=str(point.id)) for point in documents
    ]
    return CellHits(
        hits, len(points) >= DOCSEARCH_DEFAULT_LIMIT, documents if details else None
    )


def document_details(source: str, points: list[Any]) -> list[HeatmapHit]:
    if not points:
        return []
    pg = get_pg_for_source(source)
    metadata = pg.fetch_docs([str(point.id) for point in points if point.id])
    return [
        hit_from_result(result)
        for point in points
        if (result := _format_document_result(point, metadata, source)) is not None
    ]


def query_context(source: str, cell: CellSearch):
    db, pg = get_db_for_source(source), get_pg_for_source(source)
    filters = core_filters(cell)
    _resolve_chunk_search_filters(filters, db, pg, source)
    return db, pg, filters


def prepare_paragraph_hits(db, pg, results, query: str, source: str) -> CellHits:
    defaults = SYSTEM_SEARCH_DEFAULTS
    built = prepare_chunk_results(
        pg=pg,
        db=db,
        results=results,
        data_source=source,
        source=source,
        limit=QUERY_CELL_LIMIT,
        min_chunk_size=defaults["min_chunk_size"],
        query=query,
        field_boost=defaults["field_boost"],
        field_boost_fields=defaults["field_boost_fields"],
        auto_min_score=defaults["auto_min_score"],
        deduplicate=defaults["deduplicate"],
    )
    hits = [hit_from_result(result) for result in (built or [])]
    return CellHits(
        hits, len(results) >= QUERY_CELL_LIMIT or len(hits) >= QUERY_CELL_LIMIT
    )


async def search_cell(source: str, cell: CellSearch, details: bool = False) -> CellHits:
    if not cell.query:
        return await run_in_threadpool(document_hits, source, cell, details)

    db, pg, filters = await run_in_threadpool(query_context, source, cell)
    defaults = SYSTEM_SEARCH_DEFAULTS
    combo = UI_MODEL_COMBOS[get_default_model_combo()]
    sections = default_section_types()
    raw = await _run_search_chunks(
        cell.query,
        limit=QUERY_CELL_LIMIT,
        dense_weight=defaults["dense_weight"],
        db=db,
        filters=filters,
        rerank=defaults["rerank"],
        recency_boost=defaults["recency_boost"],
        recency_weight=defaults["recency_weight"],
        recency_scale_days=defaults["recency_scale_days"],
        section_types=sections.split(",") if sections else None,
        keyword_boost_short_queries=defaults["keyword_boost_short_queries"],
        min_chunk_size=defaults["min_chunk_size"],
        dense_model=combo["embedding_model"],
        rerank_model=combo.get("reranker_model"),
        max_rerank_candidates=combo.get("rerank_model_page_size") or 0,
    )
    return await run_in_threadpool(
        prepare_paragraph_hits, db, pg, raw, cell.query, source
    )
