"""Tests for _deduplicate_results in the search route."""

from ui.backend.routes.search import _deduplicate_results
from ui.backend.schemas import SearchResult


def _make_result(**overrides) -> SearchResult:
    defaults = {
        "chunk_id": "chunk-1",
        "doc_id": "doc-1",
        "text": "Some text",
        "page_num": 1,
        "headings": [],
        "score": 0.9,
        "title": "Report A",
        "year": "2024",
        "metadata": {},
    }
    defaults.update(overrides)
    return SearchResult(**defaults)


def test_empty_input():
    assert _deduplicate_results([]) == []


def test_no_duplicates():
    results = [
        _make_result(chunk_id="c1", text="First chunk"),
        _make_result(chunk_id="c2", text="Second chunk"),
        _make_result(chunk_id="c3", text="Third chunk"),
    ]
    assert len(_deduplicate_results(results)) == 3


def test_removes_duplicate_text():
    results = [
        _make_result(
            chunk_id="c1", doc_id="d1", text="Same text", year="2024", score=0.9
        ),
        _make_result(
            chunk_id="c2", doc_id="d2", text="Same text", year="2024", score=0.8
        ),
    ]
    deduped = _deduplicate_results(results)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "c1"


def test_keeps_later_year():
    results = [
        _make_result(chunk_id="c1", text="Shared", year="2022", score=0.95),
        _make_result(chunk_id="c2", text="Shared", year="2024", score=0.8),
    ]
    deduped = _deduplicate_results(results)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "c2"


def test_breaks_year_tie_by_score():
    results = [
        _make_result(chunk_id="c1", text="Tied", year="2024", score=0.7),
        _make_result(chunk_id="c2", text="Tied", year="2024", score=0.9),
    ]
    deduped = _deduplicate_results(results)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "c2"


def test_keeps_first_when_equal():
    results = [
        _make_result(chunk_id="c1", text="Equal", year="2024", score=0.9),
        _make_result(chunk_id="c2", text="Equal", year="2024", score=0.9),
    ]
    deduped = _deduplicate_results(results)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "c1"


def test_trims_whitespace():
    results = [
        _make_result(chunk_id="c1", text="  Some text  ", year="2023"),
        _make_result(chunk_id="c2", text="Some text", year="2024"),
    ]
    deduped = _deduplicate_results(results)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "c2"


def test_handles_missing_year():
    results = [
        _make_result(chunk_id="c1", text="Content", year=None, score=0.8),
        _make_result(chunk_id="c2", text="Content", year="2024", score=0.7),
    ]
    deduped = _deduplicate_results(results)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "c2"


def test_three_way_dedup():
    results = [
        _make_result(chunk_id="c1", text="Triple", year="2020", score=0.9),
        _make_result(chunk_id="c2", text="Triple", year="2024", score=0.5),
        _make_result(chunk_id="c3", text="Triple", year="2022", score=0.95),
    ]
    deduped = _deduplicate_results(results)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "c2"


def test_preserves_order_of_unique_results():
    results = [
        _make_result(chunk_id="c1", text="Alpha"),
        _make_result(chunk_id="c2", text="Beta"),
        _make_result(chunk_id="c3", text="Gamma"),
    ]
    deduped = _deduplicate_results(results)
    assert [r.chunk_id for r in deduped] == ["c1", "c2", "c3"]
