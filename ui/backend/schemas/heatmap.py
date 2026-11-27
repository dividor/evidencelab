"""Inputs and display data shared by the Heatmapper service and its adapters."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_ROWS = 4
MAX_COLUMNS = 6
MAX_CELLS = MAX_ROWS * MAX_COLUMNS

AxisId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
AxisValue = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
QueryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
Metric = Literal["documents", "chunks"]
FilterValues = (
    AxisValue | Annotated[list[AxisValue], Field(min_length=1, max_length=20)]
)


class HeatmapInputError(ValueError):
    """A validation error that may be shown to the caller."""


class HeatmapRequest(BaseModel):
    """A corpus, two dimensions, and optional queries and facet selections."""

    model_config = ConfigDict(extra="forbid")

    data_source: AxisId | None = Field(
        default=None,
        description=(
            "Configured document collection key. Omit only when the deployment "
            "has one collection or specifies a default."
        ),
    )
    row_dimension: AxisId = Field(
        description=(
            "Configured facet key, such as organization, or 'queries' for one search "
            "query per row. Choose a different field from column_dimension. "
            "Report titles are unavailable."
        ),
    )
    column_dimension: AxisId = Field(
        description=(
            "Configured facet key with at most 20 available categories, or "
            "published_year. Choose a different field from row_dimension."
        ),
    )
    row_values: (
        Annotated[list[AxisValue], Field(min_length=1, max_length=MAX_ROWS)] | None
    ) = Field(
        default=None,
        description=(
            "Exact facet values to display as rows, such as UNDP and UNICEF. "
            "Omit to use the most frequent values. Use row_queries for query rows."
        ),
        examples=[["UNDP", "UNICEF"]],
    )
    column_values: (
        Annotated[list[AxisValue], Field(min_length=1, max_length=MAX_COLUMNS)] | None
    ) = Field(
        default=None,
        description=(
            "Exact facet values to display as columns, such as the strings "
            "'2023' and '2024'. Omit to use the most frequent values."
        ),
        examples=[["2023", "2024"]],
    )
    query: QueryText | None = Field(
        default=None,
        description=(
            "One search query applied to every cell when the rows and columns "
            "are facets. Leave unset for indexed document counts or query rows."
        ),
    )
    row_queries: (
        Annotated[list[QueryText], Field(min_length=1, max_length=MAX_ROWS)] | None
    ) = Field(
        default=None,
        description=(
            "One distinct search query per row, in display order. Required when "
            "row_dimension is 'queries'. Leave query and row_values unset."
        ),
    )
    filters: Annotated[dict[AxisId, FilterValues], Field(max_length=12)] = Field(
        default_factory=dict,
        description=(
            "Facet restrictions for the whole grid. Each key takes one exact value "
            "or a list of values. Commas inside a string are part of the facet value."
        ),
        examples=[{"organization": ["UNDP", "UNICEF"], "published_year": "2024"}],
    )
    metric: Metric = Field(
        default="documents",
        description=(
            "Use 'documents' to count documents or 'chunks' to count matching "
            "paragraphs. Paragraph counts require query or row_queries."
        ),
    )

    @model_validator(mode="after")
    def validate_modes(self) -> Self:
        if self.row_dimension == self.column_dimension:
            raise ValueError("Choose different row and column dimensions.")
        if (
            self.column_dimension in {"queries", "title"}
            or self.row_dimension == "title"
        ):
            raise ValueError(
                "Only facet columns and facet or query rows are supported."
            )
        if self.row_dimension == "queries":
            if not self.row_queries or self.query or self.row_values:
                raise ValueError("Supply only row_queries for search query rows.")
        elif self.row_queries:
            raise ValueError("Use row_queries with the queries row dimension.")
        if self.metric == "chunks" and not (self.query or self.row_queries):
            raise ValueError("The Paragraphs metric requires a search query.")
        for values in (self.row_values, self.column_values, self.row_queries):
            if values and len(values) != len(set(values)):
                raise ValueError("Axis selections must be unique.")
        return self


class HeatmapCellRequest(BaseModel):
    """Replay one cell using the arguments returned by the grid."""

    model_config = ConfigDict(extra="forbid")

    grid: HeatmapRequest = Field(description="Copy request from the heatmap result.")
    row: int = Field(ge=0, lt=MAX_ROWS, description="Zero-based displayed row index.")
    column: int = Field(
        ge=0, lt=MAX_COLUMNS, description="Zero-based displayed column index."
    )
    cutoff: Annotated[float, Field(allow_inf_nan=False, ge=0)] | None = Field(
        default=None, description="Copy cutoff from the heatmap result, including null."
    )
    fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")] = Field(
        description="Copy fingerprints[row][column] from the heatmap result."
    )
    offset: int = Field(
        default=0,
        ge=0,
        lt=50000,
        description="Use zero for the first page or copy next_offset from the prior page.",
    )


class HeatmapAxisValue(BaseModel):
    value: str
    label: str


class HeatmapAxis(BaseModel):
    dimension: str
    label: str
    values: list[HeatmapAxisValue]
    omitted: int = 0


class HeatmapGrid(BaseModel):
    request: HeatmapRequest
    rows: HeatmapAxis
    columns: HeatmapAxis
    row_dimensions: dict[str, str]
    column_dimensions: dict[str, str]
    counts: list[list[int]]
    capped_cells: list[list[bool]]
    fingerprints: list[list[str]]
    cutoff: float | None
    candidate_limit: int


class HeatmapDocument(BaseModel):
    doc_id: str
    title: str
    organization: str | None = None
    year: str | None = None
    link: str | None = None
    paragraph_count: int | None = None


class HeatmapCell(BaseModel):
    count: int
    documents: list[HeatmapDocument]
    total_documents: int
    next_offset: int | None = None
