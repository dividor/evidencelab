"""Tests for grid planning, retrieval, counts, and selected-cell replay."""

from secrets import token_urlsafe
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import anyio
import pytest
from pydantic import ValidationError

from ui.backend.schemas import Facets, FacetValue
from ui.backend.schemas.heatmap import (
    HeatmapCellRequest,
    HeatmapInputError,
    HeatmapRequest,
)
from ui.backend.services import heatmap, heatmap_search
from ui.backend.services.heatmap_axes import plan_axes
from ui.backend.services.heatmap_search import CellHits, CellSearch, HeatmapHit

pytestmark = pytest.mark.unit


@pytest.fixture
def facets():
    return Facets(
        filter_fields={
            "organization": "Organization",
            "published_year": "Year Published",
        },
        facets={
            "organization": [
                FacetValue(value="WHO", count=3),
                FacetValue(value="UNICEF", count=8),
            ],
            "published_year": [
                FacetValue(value="2024", count=5),
                FacetValue(value="2022", count=4),
                FacetValue(value="2023", count=3),
            ],
        },
    )


def attribute_request(**changes):
    return HeatmapRequest.model_validate(
        {
            "data_source": "uneg",
            "row_dimension": "organization",
            "column_dimension": "published_year",
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"row_dimension": "published_year"},
        {"row_dimension": "queries"},
        {"row_dimension": "title"},
        {"row_queries": ["education"]},
        {"metric": "chunks"},
        {"row_values": ["WHO", "WHO"]},
        {"column_values": ["1", "2", "3", "4", "5", "6", "7"]},
        {"metric": "sum"},
        {"injected_parameter": "unexpected"},
    ],
)
def test_request_rejects_invalid_grid(changes):
    with pytest.raises(ValidationError):
        attribute_request(**changes)


def test_axis_planning_preserves_filter_values_and_orders_labels(facets):
    request = attribute_request(
        row_values=["WHO", "UNICEF"], filters={"published_year": ["2024", "2023"]}
    )
    plan = plan_axes(request, facets, 24)
    assert plan.request.row_values == ["UNICEF", "WHO"]
    assert plan.request.column_values == ["2023", "2024"]
    assert plan.cell_count == 4
    assert plan.columns.label == "Year Published"
    assert plan.column_dimensions == facets.filter_fields

    with pytest.raises(HeatmapInputError, match="permits 3 cells"):
        plan_axes(request, facets, 3)
    with pytest.raises(HeatmapInputError, match="selection is unavailable"):
        plan_axes(attribute_request(row_values=["Unknown"]), facets, 24)


def test_default_axis_caps_pick_highest_facet_counts(facets):
    facets.facets["organization"] += [
        FacetValue(value=name, count=count)
        for name, count in [("Agency A", 4), ("Agency B", 5), ("Agency C", 6)]
    ]
    plan = plan_axes(attribute_request(), facets, 24)
    assert plan.request.row_values == ["Agency A", "Agency B", "Agency C", "UNICEF"]
    assert plan.rows.omitted == 1


@pytest.mark.asyncio
async def test_builder_schedules_each_cell_and_keeps_input_order(facets, monkeypatch):
    request = attribute_request(filters={"language": "English"})
    plan = plan_axes(request, facets, 24)
    calls = []
    active, peak = 0, 0

    async def search(source, cell, details):
        nonlocal active, peak
        assert source == "uneg" and not details
        assert cell.filters["language"] == "English"
        active += 1
        peak = max(peak, active)
        calls.append((cell.filters["organization"], cell.filters["published_year"]))
        await anyio.sleep(0.005 if cell.filters["organization"] == "UNICEF" else 0)
        active -= 1
        count = int(cell.filters["published_year"][-1])
        return CellHits(
            [HeatmapHit(str(index), str(index)) for index in range(count)], False
        )

    monkeypatch.setattr(heatmap, "search_cell", search)
    grid = await heatmap.build_heatmap(plan)

    assert set(calls) == {
        (organization, year)
        for organization in ["UNICEF", "WHO"]
        for year in ["2022", "2023", "2024"]
    }
    assert len(calls) == 6 and peak == 3
    assert grid.counts == [[2, 3, 4], [2, 3, 4]]
    assert grid.cutoff is None


@pytest.mark.asyncio
async def test_builder_propagates_retrieval_failure(facets, monkeypatch):
    monkeypatch.setattr(
        heatmap, "search_cell", AsyncMock(side_effect=RuntimeError("backend down"))
    )
    with pytest.raises(ExceptionGroup) as result:
        await heatmap.build_heatmap(plan_axes(attribute_request(), facets, 24))
    assert any(isinstance(error, RuntimeError) for error in result.value.exceptions)


def test_query_counts_and_cutoff_match_heatmap_rules(facets):
    request = attribute_request(
        row_dimension="queries",
        row_queries=["School meals"],
        column_values=["2024", "2022"],
    )
    plan = plan_axes(request, facets, 24)
    first = CellHits(
        [
            HeatmapHit("1", "A", 1.0, "Same title", "2022", "WHO"),
            HeatmapHit("2", "B", 0.9, "Same title", "2022", "WHO"),
            HeatmapHit("3", "C", 0.95, ""),
            HeatmapHit("4", "D", 0.2, "Below cutoff"),
        ],
        True,
    )
    last = CellHits([HeatmapHit("5", "E", 0.0, "Unscored")], False)

    grid = heatmap.assemble_grid(plan, [first, last])
    assert grid.cutoff == pytest.approx(0.84)
    assert grid.counts == [[1, 1]]
    assert grid.capped_cells == [[True, False]]
    assert heatmap.counted_hits(first, grid.cutoff, "chunks")[0] == 3
    assert heatmap.cell_search(request, "School meals", "2024") == CellSearch(
        "School meals", {"published_year": "2024"}
    )


def test_cutoff_handles_identical_or_missing_finite_scores():
    assert heatmap.automatic_cutoff(
        [CellHits([HeatmapHit("1", "A", 1)], False)]
    ) == pytest.approx(1.03)
    assert (
        heatmap.automatic_cutoff(
            [CellHits([HeatmapHit("1", "A", float("nan"))], False)]
        )
        is None
    )


def test_document_retrieval_excludes_points_with_empty_payloads(monkeypatch):
    points = [
        SimpleNamespace(id="one", payload={"map_title": "One"}),
        SimpleNamespace(id="two", payload={}),
    ]
    find = Mock(return_value=(points, None, None))
    monkeypatch.setattr(heatmap_search, "find_document_points", find)
    monkeypatch.setattr(heatmap_search, "get_db_for_source", Mock())
    monkeypatch.setattr(heatmap_search, "get_pg_for_source", Mock())
    result = heatmap_search.document_hits(
        "uneg",
        CellSearch("", {"country": ["Congo, Dem. Rep."], "language": "English"}),
        True,
    )
    assert [hit.doc_id for hit in result.hits] == ["one"]
    assert result.points == points[:1]
    assert find.call_args.kwargs["core_filters"] == {
        "country": ["Congo, Dem. Rep."],
        "language": "en",
    }


@pytest.mark.asyncio
async def test_drill_down_replays_membership_and_pages_documents(monkeypatch):
    grid = attribute_request(
        query="Education",
        metric="chunks",
        row_values=["WHO"],
        column_values=["2024"],
    )
    hits = [HeatmapHit(str(i), str(i), 0.9, f"Title {i}") for i in range(23)]
    result = CellHits(hits, False)
    search = AsyncMock(return_value=result)
    monkeypatch.setattr(heatmap, "search_cell", search)
    request = HeatmapCellRequest(
        grid=grid, row=0, column=0, cutoff=0.8, fingerprint=heatmap.membership(hits, 23)
    )
    first = await heatmap.heatmap_cell("uneg", request)
    assert first.count == first.total_documents == 23
    assert len(first.documents) == 20 and first.next_offset == 20
    assert all(document.paragraph_count == 1 for document in first.documents)
    search.assert_awaited_with(
        "uneg",
        CellSearch("Education", {"organization": "WHO", "published_year": "2024"}),
        True,
    )
    second = await heatmap.heatmap_cell(
        "uneg", request.model_copy(update={"offset": 20})
    )
    assert [document.doc_id for document in second.documents] == ["20", "21", "22"]
    assert second.next_offset is None
    search.return_value = CellHits(
        hits[:-1] + [HeatmapHit("99", "99", 0.9, "Different")], False
    )
    with pytest.raises(HeatmapInputError, match="evidence has changed"):
        await heatmap.heatmap_cell("uneg", request)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        f"https://user:{token_urlsafe(16)}@example.org/",
        "https://example.org/\nword",
        "https://[invalid",
        "//example.org/",
        "https://example.org\\@evil.org/",
    ],
)
def test_document_links_reject_unsafe_values(url):
    assert heatmap.safe_document_link(HeatmapHit("1", "1", report_url=url)) is None
    assert (
        heatmap.safe_document_link(
            HeatmapHit("1", "1", pdf_url="https://example.org/file.pdf")
        )
        == "https://example.org/file.pdf"
    )


@pytest.mark.asyncio
async def test_query_cell_uses_rest_filter_resolution_and_result_preparation(
    monkeypatch,
):
    db = Mock()
    db.indexed_payload_keys.return_value = set()
    db.facet_documents.return_value = {}
    pg = Mock()
    pg.fetch_doc_ids_by_language.return_value = ["doc"]
    pg.fetch_docs.return_value = {
        "doc": {"map_title": "School Nutrition", "map_published_year": "2024"},
    }
    text = "School meal evaluations track education and food security outcomes. " * 5
    pg.fetch_chunks.return_value = {"chunk": {"sys_text": text, "sys_page_num": 1}}
    raw = SimpleNamespace(
        id="chunk",
        score=0.8,
        payload={"doc_id": "doc", "sys_doc_id": "doc", "sys_text": text},
    )
    search = Mock(return_value=[raw])
    monkeypatch.setattr(heatmap_search, "get_db_for_source", lambda _: db)
    monkeypatch.setattr(heatmap_search, "get_pg_for_source", lambda _: pg)
    monkeypatch.setattr("ui.backend.routes.search.search_chunks", search)
    combo = heatmap_search.UI_MODEL_COMBOS[heatmap_search.get_default_model_combo()]
    monkeypatch.setitem(combo, "rerank_model_page_size", 25)
    result = await heatmap_search.search_cell(
        "uneg",
        CellSearch("school meals", {"language": "English", "published_year": "2024"}),
    )
    assert result.hits == [HeatmapHit("chunk", "doc", 0.8, "School Nutrition", "2024")]
    pg.fetch_doc_ids_by_language.assert_called_once_with(["en"])
    assert search.call_args.kwargs["filters"] == {
        "doc_id": "doc",
        "published_year": ["2024"],
    }
    assert search.call_args.kwargs["max_rerank_candidates"] == 25


def test_filter_only_drill_down_formats_the_same_document_points(facets, monkeypatch):
    grid_request = attribute_request(row_values=["UNICEF"], column_values=["2024"])
    points = [
        SimpleNamespace(
            id="doc",
            payload={
                "map_title": "School Nutrition",
                "map_organization": "UNICEF",
                "map_published_year": "2024",
                "map_pdf_url": "https://example.org/report.pdf",
            },
        )
    ]
    result = CellHits([HeatmapHit("doc", "doc")], False, points)
    monkeypatch.setattr(
        heatmap_search,
        "get_pg_for_source",
        lambda _: Mock(
            fetch_docs=Mock(return_value={}),
        ),
    )
    grid = heatmap.assemble_grid(plan_axes(grid_request, facets, 24), [result])
    request = HeatmapCellRequest(
        grid=grid.request, row=0, column=0, fingerprint=grid.fingerprints[0][0]
    )
    detail = heatmap.detail_page("uneg", result, request)
    assert detail.count == detail.total_documents == 1
    assert detail.documents[0].title == "School Nutrition"
    assert detail.documents[0].organization == "UNICEF"
