"""Count independently filtered cells and replay a selected cell."""

import hashlib
import json
import math
from itertools import product
from urllib.parse import urlsplit

import anyio
from fastapi.concurrency import run_in_threadpool

from ui.backend.routes.search import DOCSEARCH_DEFAULT_LIMIT
from ui.backend.schemas.heatmap import (
    HeatmapCell,
    HeatmapCellRequest,
    HeatmapDocument,
    HeatmapGrid,
    HeatmapInputError,
    HeatmapRequest,
    Metric,
)
from ui.backend.services.heatmap_axes import HeatmapPlan, configured_fields
from ui.backend.services.heatmap_search import (
    QUERY_CELL_LIMIT,
    CellHits,
    CellSearch,
    HeatmapHit,
    document_details,
    search_cell,
)

_GRID_TIMEOUT = 40
_CELL_LIMITER = anyio.CapacityLimiter(3)
_PAGE_SIZE = 20


def cell_search(request: HeatmapRequest, row: str, column: str) -> CellSearch:
    filters = {**request.filters, request.column_dimension: column}
    if request.row_dimension == "queries":
        return CellSearch(row, filters)
    return CellSearch(request.query or "", {**filters, request.row_dimension: row})


def automatic_cutoff(cells: list[CellHits]) -> float | None:
    scores = [
        hit.score
        for cell in cells
        for hit in cell.hits
        if hit.score != 0 and math.isfinite(hit.score)
    ]
    if not scores:
        return None
    low = max(0, min(scores))
    high = max(low, max(scores))
    if low == high:
        padding = max(0.01, low * 0.05)
        low, high = max(0, low - padding), high + padding
    return high - 0.2 * (high - low)


def counted_hits(
    cell: CellHits, cutoff: float | None, metric: Metric
) -> tuple[int, list[HeatmapHit]]:
    eligible = [
        hit
        for hit in cell.hits
        if hit.score == 0
        or (math.isfinite(hit.score) and (cutoff is None or hit.score >= cutoff))
    ]
    if metric == "chunks" or not any(hit.score > 0 for hit in eligible):
        return len(eligible), eligible
    eligible = [hit for hit in eligible if any(hit.identity)]
    return len({hit.identity for hit in eligible}), eligible


def membership(hits: list[HeatmapHit], count: int) -> str:
    ids = sorted((hit.doc_id, hit.hit_id) for hit in hits)
    return hashlib.sha256(json.dumps([count, ids]).encode()).hexdigest()[:32]


def assemble_grid(plan: HeatmapPlan, flat_cells: list[CellHits]) -> HeatmapGrid:
    cutoff = automatic_cutoff(flat_cells)
    counts, capped, fingerprints = [], [], []
    columns = len(plan.columns.values)
    for start in range(0, len(flat_cells), columns):
        row_cells = flat_cells[start : start + columns]
        included = [
            counted_hits(cell, cutoff, plan.request.metric) for cell in row_cells
        ]
        counts.append([count for count, _ in included])
        capped.append([cell.capped for cell in row_cells])
        fingerprints.append([membership(hits, count) for count, hits in included])
    queried = bool(plan.request.query or plan.request.row_queries)
    return HeatmapGrid(
        request=plan.request,
        rows=plan.rows,
        columns=plan.columns,
        row_dimensions=plan.row_dimensions,
        column_dimensions=plan.column_dimensions,
        counts=counts,
        capped_cells=capped,
        fingerprints=fingerprints,
        cutoff=cutoff,
        candidate_limit=QUERY_CELL_LIMIT if queried else DOCSEARCH_DEFAULT_LIMIT,
    )


async def limited_search(
    source: str, cell: CellSearch, details: bool = False
) -> CellHits:
    async with _CELL_LIMITER:
        return await search_cell(source, cell, details)


async def build_heatmap(plan: HeatmapPlan) -> HeatmapGrid:
    """Run one independent search per cell, with a shared process-level limit."""
    request = plan.request
    assert request.data_source is not None
    source = request.data_source
    cells = [
        cell_search(request, row.value, column.value)
        for row, column in product(plan.rows.values, plan.columns.values)
    ]
    indexed: dict[int, CellHits] = {}

    async def collect(index: int, cell: CellSearch) -> None:
        indexed[index] = await limited_search(source, cell)

    with anyio.fail_after(_GRID_TIMEOUT):
        async with anyio.create_task_group() as group:
            for index, cell in enumerate(cells):
                group.start_soon(collect, index, cell)
        return await run_in_threadpool(assemble_grid, plan, list_by_index(indexed))


def list_by_index(results: dict[int, CellHits]) -> list[CellHits]:
    return [results[index] for index in range(len(results))]


def validate_cell(source: str, request: HeatmapCellRequest) -> CellSearch:
    grid = request.grid
    configured_fields(grid, source)
    rows = grid.row_queries if grid.row_dimension == "queries" else grid.row_values
    columns = grid.column_values
    if (
        not rows
        or not columns
        or request.row >= len(rows)
        or request.column >= len(columns)
    ):
        raise HeatmapInputError("Select one of the cells returned by the heatmap.")
    return cell_search(grid, rows[request.row], columns[request.column])


def safe_document_link(hit: HeatmapHit) -> str | None:
    for url in (hit.report_url, hit.pdf_url):
        if url and safe_web_url(url):
            return url
    return None


def safe_web_url(url: str) -> bool:
    if (
        not isinstance(url, str)
        or "\\" in url
        or any(ord(char) <= 32 or ord(char) == 127 for char in url)
    ):
        return False
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme in {"https", "http"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def summarize_document(
    hit: HeatmapHit, paragraphs: int | None = None
) -> HeatmapDocument:
    return HeatmapDocument(
        doc_id=hit.doc_id,
        title=hit.title or "Untitled document",
        organization=hit.organization,
        year=hit.year,
        link=safe_document_link(hit),
        paragraph_count=paragraphs,
    )


def document_groups(
    hits: list[HeatmapHit], metric: Metric
) -> list[tuple[HeatmapHit, int | None]]:
    grouped: dict[str | tuple[str, str, str], list[HeatmapHit]] = {}
    has_positive = any(hit.score > 0 for hit in hits)
    for hit in hits:
        key: str | tuple[str, str, str] = (
            hit.identity if metric == "documents" and has_positive else hit.doc_id
        )
        grouped.setdefault(key, []).append(hit)
    return [
        (group[0], len(group) if metric == "chunks" else None)
        for group in grouped.values()
    ]


def detail_page(
    source: str, result: CellHits, request: HeatmapCellRequest
) -> HeatmapCell:
    metric = request.grid.metric
    count, included = counted_hits(result, request.cutoff, metric)
    if membership(included, count) != request.fingerprint:
        raise HeatmapInputError(
            "The matching evidence has changed. Generate the heatmap again."
        )
    start, end = request.offset, request.offset + _PAGE_SIZE
    page: list[tuple[HeatmapHit, int | None]]
    if result.points is not None:
        total = len(result.points)
        page = [
            (hit, None) for hit in document_details(source, result.points[start:end])
        ]
    else:
        groups = document_groups(included, metric)
        total = len(groups)
        page = groups[start:end]
    return HeatmapCell(
        count=count,
        total_documents=total,
        documents=[summarize_document(hit, paragraphs) for hit, paragraphs in page],
        next_offset=end if end < total else None,
    )


async def heatmap_cell(source: str, request: HeatmapCellRequest) -> HeatmapCell:
    with anyio.fail_after(_GRID_TIMEOUT):
        cell = await run_in_threadpool(validate_cell, source, request)
        result = await limited_search(source, cell, details=True)
        return await run_in_threadpool(detail_page, source, result, request)
