"""Authenticated MCP entry points and text responses for Heatmapper."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated
from urllib.parse import urlencode, urlsplit, urlunsplit

import anyio
from mcp.types import CallToolResult, TextContent
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from mcp_server import oauth
from mcp_server.audit import log_mcp_call, request_auth, request_client_ip
from mcp_server.data_source_access import (
    MCPSourceDenied,
    resolve_mcp_source,
    source_keys,
)
from mcp_server.rate_limit import (
    McpRateLimitExceeded,
    check_caller_rate_limit,
    rate_limit_allowance,
)
from ui.backend.schemas.heatmap import (
    MAX_CELLS,
    HeatmapCellRequest,
    HeatmapGrid,
    HeatmapInputError,
    HeatmapRequest,
)

logger = logging.getLogger(__name__)
_GRID_CALLS = anyio.CapacityLimiter(2)


def escape_table_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def text_table(grid: HeatmapGrid) -> str:
    metric = "Documents" if grid.request.metric == "documents" else "Paragraphs"
    heading = f"{metric} · {grid.rows.label} × {grid.columns.label}"
    if grid.cutoff is not None:
        heading += (
            "\nQuery counts use the top matches that pass the shared score cutoff."
        )
    header = [grid.rows.label, *(value.label for value in grid.columns.values)]
    table = [
        "| " + " | ".join(map(escape_table_value, header)) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    capped = False
    for value, counts, caps in zip(grid.rows.values, grid.counts, grid.capped_cells):
        numbers = [f"{count}{'*' if cap else ''}" for count, cap in zip(counts, caps)]
        table.append(
            "| " + " | ".join([escape_table_value(value.label), *numbers]) + " |"
        )
        capped |= any(caps)
    if capped:
        table.append(
            f"\n* A cell reached its retrieval limit of {grid.candidate_limit:,} candidates."
        )
    if grid.rows.omitted or grid.columns.omitted:
        table.append(
            f"\nValues outside this grid: {grid.rows.omitted} rows and "
            f"{grid.columns.omitted} columns."
        )
    return heading + "\n\n" + "\n".join(table)


def web_link(grid: HeatmapGrid, dataset: str) -> str:
    """Build the existing web Heatmapper link from configured origin and grid state."""
    from ui.backend.services.heatmap import safe_web_url

    base = oauth._APP_BASE_URL
    if not safe_web_url(base):
        raise RuntimeError("APP_BASE_URL must be a valid web URL")
    url = urlsplit(base)
    request = grid.request
    params: list[tuple[str, str]] = [
        ("tab", "heatmap"),
        ("dataset", dataset),
        ("hm_row", request.row_dimension),
        ("hm_col", request.column_dimension),
        ("hm_metric", request.metric),
        ("hm_run", "true"),
    ]
    if request.query:
        params.append(("hm_q", request.query))
    params.extend(("hm_row_q", value) for value in request.row_queries or [])
    if grid.cutoff is not None:
        params.append(("hm_sens", str(grid.cutoff)))
    filters = {
        **request.filters,
        request.column_dimension: request.column_values or [],
    }
    if request.row_dimension != "queries":
        filters[request.row_dimension] = request.row_values or []
    params.extend(
        (field, ",".join(value) if isinstance(value, list) else value)
        for field, value in filters.items()
    )
    return urlunsplit((url.scheme, url.netloc, url.path or "/", urlencode(params), ""))


async def audited_call(
    tool: str,
    inputs: dict,
    operation: Callable[[], Awaitable[CallToolResult]],
) -> CallToolResult:
    started = time.monotonic()
    summary = None
    error_message = None
    status = "error"
    try:
        result = await operation()
        status = "ok"
        data = result.structuredContent or {}
        summary = (
            f"rows={len(data['counts'])}"
            if "counts" in data
            else f"documents={data.get('total_documents', 0)}"
        )
        return result
    except (McpRateLimitExceeded, HeatmapInputError, MCPSourceDenied) as error:
        error_message = str(error)
    except (TimeoutError, anyio.WouldBlock):
        error_message = (
            "Heatmapper is busy or took too long. Try again with a smaller grid."
        )
    except Exception:
        logger.exception("Heatmapper tool failed: %s", tool)
        error_message = "Heatmapper could not complete the search. Try again later."
    finally:
        log_mcp_call(
            tool_name=tool,
            auth_info=request_auth.get(),
            client_ip=request_client_ip.get(),
            input_params=inputs,
            output_summary=summary or "status=error",
            duration_ms=(time.monotonic() - started) * 1000,
            status=status,
            error_message=error_message,
        )
    return CallToolResult(
        content=[TextContent(type="text", text=error_message)], isError=True
    )


async def read_source(data_source: str | None) -> str:
    try:
        return await resolve_mcp_source(data_source)
    except ValueError:
        raise HeatmapInputError("Choose a configured data source.") from None


async def heatmap(
    request: Annotated[
        HeatmapRequest, Field(description="Define the heatmap to build.")
    ],
) -> CallToolResult:
    """Compare counts across two dimensions in a heatmap with up to 24 cells.

    For document counts by organization and year, set row_dimension to
    organization and column_dimension to published_year. To compare topics,
    set row_dimension to queries and supply row_queries.
    Use search with include_facets enabled to discover facet keys and values.
    Without a query, count indexed documents. With a query, count documents
    or paragraphs among the top matches that pass a shared score cutoff.
    Use at most 4 rows and 6 columns. If the deployment allows fewer cells,
    narrow the grid using row_values and column_values.
    Returns display axes and counts in structuredContent and a text table in content.
    """

    async def run() -> CallToolResult:
        from ui.backend.services.heatmap import build_heatmap
        from ui.backend.services.heatmap_axes import plan_heatmap

        check_caller_rate_limit("search")
        source = await read_source(request.data_source)
        normalized = request.model_copy(update={"data_source": source})
        max_cells = min(MAX_CELLS, rate_limit_allowance("search") - 1)
        _GRID_CALLS.acquire_nowait()
        try:
            with anyio.fail_after(45):
                plan = await run_in_threadpool(
                    plan_heatmap, normalized, source, max_cells
                )
                check_caller_rate_limit("search", cost=plan.cell_count)
                grid = await build_heatmap(plan)
            dataset, _ = await run_in_threadpool(source_keys, request.data_source)
            return CallToolResult(
                content=[TextContent(type="text", text=text_table(grid))],
                structuredContent={
                    **grid.model_dump(mode="json"),
                    "web_url": web_link(grid, dataset),
                },
            )
        finally:
            _GRID_CALLS.release()

    return await audited_call(
        "heatmap",
        {
            "data_source": request.data_source,
            "row_dimension": request.row_dimension,
            "column_dimension": request.column_dimension,
            "metric": request.metric,
        },
        run,
    )


async def heatmap_cell(
    request: Annotated[
        HeatmapCellRequest, Field(description="Select a cell and page.")
    ],
) -> CallToolResult:
    """Page through documents from one cell of an existing heatmap.

    The app calls this tool with the displayed row and column indexes and the
    original heatmap result's request, cutoff, and cell fingerprint. Each page
    returns up to 20 documents. Use next_offset to fetch the next page.
    """

    async def run() -> CallToolResult:
        from ui.backend.services.heatmap import heatmap_cell as build_cell

        check_caller_rate_limit("search")
        source = await read_source(request.grid.data_source)
        cell = await build_cell(source, request)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Found {cell.total_documents} matching documents.",
                )
            ],
            structuredContent=cell.model_dump(mode="json"),
        )

    return await audited_call(
        "heatmap_cell",
        {
            "data_source": request.grid.data_source,
            "row": request.row,
            "column": request.column,
            "metric": request.grid.metric,
            "offset": request.offset,
        },
        run,
    )
