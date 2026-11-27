"""Plan bounded cross-tabulations from the facets used by the web Heatmapper."""

from dataclasses import dataclass

from pipeline.db import get_default_filter_fields, get_taxonomy_filter_fields
from ui.backend.routes.search import read_filter_facets
from ui.backend.schemas import Facets, FacetValue
from ui.backend.schemas.heatmap import (
    MAX_COLUMNS,
    MAX_ROWS,
    HeatmapAxis,
    HeatmapAxisValue,
    HeatmapInputError,
    HeatmapRequest,
)
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source

_COLUMN_CARDINALITY = 20


@dataclass
class HeatmapPlan:
    request: HeatmapRequest
    rows: HeatmapAxis
    columns: HeatmapAxis
    row_dimensions: dict[str, str]
    column_dimensions: dict[str, str]

    @property
    def cell_count(self) -> int:
        return len(self.rows.values) * len(self.columns.values)


def configured_fields(request: HeatmapRequest, source: str) -> dict[str, str]:
    fields = {**get_default_filter_fields(source), **get_taxonomy_filter_fields(source)}
    axes = set(fields) - {"title"}
    if request.column_dimension not in axes or request.row_dimension not in axes | {
        "queries"
    }:
        raise HeatmapInputError("Choose dimensions configured for this data source.")
    if set(request.filters) - (set(fields) - {"title"}):
        raise HeatmapInputError(
            "Choose facet filters configured for this data source. Title filters are unavailable."
        )
    return fields


def facet_selection(value: str | list[str]) -> list[str]:
    """Tool inputs carry literal values, including values with commas."""
    return value if isinstance(value, list) else [value]


def plan_heatmap(request: HeatmapRequest, source: str, max_cells: int) -> HeatmapPlan:
    fields = configured_fields(request, source)
    facets = read_filter_facets(
        source=source,
        db=get_db_for_source(source),
        pg=get_pg_for_source(source),
        fields=fields,
        core_filters=facet_query_filters(request.filters),
    )
    return plan_axes(request, facets, max_cells)


def facet_query_filters(filters: dict[str, str | list[str]]) -> dict[str, list[str]]:
    # Facet discovery always returns corpus values for PostgreSQL-only fields.
    # Leave those filters to the cell lookups, which resolve them to documents.
    return {
        field: facet_selection(value)
        for field, value in filters.items()
        if field not in {"language", "region"}
        and not field.startswith(("src_", "tag_"))
    }


def plan_axes(request: HeatmapRequest, facets: Facets, max_cells: int) -> HeatmapPlan:
    rows = {
        field: facets.filter_fields[field]
        for field, values in facets.facets.items()
        if field != "title" and values
    }
    columns = {
        field: label
        for field, label in rows.items()
        if field == "published_year" or len(facets.facets[field]) <= _COLUMN_CARDINALITY
    }
    if request.column_dimension not in columns:
        raise HeatmapInputError(
            "Choose a column with available values and at most 20 categories, "
            "or use Year Published."
        )
    if request.row_dimension not in rows and request.row_dimension != "queries":
        raise HeatmapInputError(
            "The row dimension has no available values for these filters."
        )

    row = select_rows(request, facets)
    column = select_axis(
        facets,
        request.column_dimension,
        request.column_values,
        request.filters.get(request.column_dimension),
        MAX_COLUMNS,
    )
    normalized = request.model_copy(
        update={
            "row_values": (
                [v.value for v in row.values]
                if request.row_dimension != "queries"
                else None
            ),
            "column_values": [v.value for v in column.values],
        }
    )
    plan = HeatmapPlan(
        normalized, row, column, {"queries": "Search query", **rows}, columns
    )
    if plan.cell_count > max_cells:
        raise HeatmapInputError(
            f"This deployment permits {max_cells} cells per heatmap. Select fewer axis values."
        )
    return plan


def select_rows(request: HeatmapRequest, facets: Facets) -> HeatmapAxis:
    if request.row_dimension == "queries":
        return HeatmapAxis(
            dimension="queries",
            label="Search query",
            values=[
                HeatmapAxisValue(value=query, label=query)
                for query in request.row_queries or []
            ],
        )
    return select_axis(
        facets,
        request.row_dimension,
        request.row_values,
        request.filters.get(request.row_dimension),
        MAX_ROWS,
    )


def select_axis(
    facets: Facets,
    field: str,
    selected: list[str] | None,
    restricted: str | list[str] | None,
    limit: int,
) -> HeatmapAxis:
    values = {item.value: item for item in facets.facets[field] if item.value}
    if restricted is not None:
        permitted = set(facet_selection(restricted))
        values = {key: item for key, item in values.items() if key in permitted}
    if selected and set(selected) - values.keys():
        raise HeatmapInputError(
            "An axis selection is unavailable for this data source and filters."
        )
    if not values:
        raise HeatmapInputError("An axis has no values for the requested filters.")
    if selected is None:
        ranked = sorted(
            values.values(), key=lambda item: (-item.count, axis_order(item))
        )
        shown = [item.value for item in ranked[:limit]]
    else:
        shown = selected
    return HeatmapAxis(
        dimension=field,
        label=facets.filter_fields[field],
        values=[
            HeatmapAxisValue(value=value, label=value)
            for value in sorted(shown, key=lambda value: axis_order(values[value]))
        ],
        omitted=len(values) - len(shown),
    )


def axis_order(item: FacetValue) -> tuple[int, int, str, str]:
    value = item.value
    if value.isascii() and value.isdecimal() and len(value) <= 12:
        return (0, int(value), value.casefold(), value)
    return (1, 0, value.casefold(), value)
