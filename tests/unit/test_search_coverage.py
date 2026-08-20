"""Tests for the concentrated-results coverage detection and the
per-document cap ("broaden results" mode) in chunk search."""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from starlette.requests import Request

from ui.backend import main as main_module
from ui.backend.routes.search import _build_search_coverage, _build_search_results
from ui.backend.schemas import SearchResult
from ui.backend.services import search_coverage as coverage_module
from ui.backend.services.search import _record_candidate_documents
from ui.backend.services.search_coverage import (
    CoverageThresholds,
    count_candidate_documents,
    is_concentrated,
    load_coverage_thresholds,
)

pytestmark = pytest.mark.unit

DEFAULTS = CoverageThresholds()


def _point(chunk_id: str, doc_id: Optional[str], **payload_extra: Any):
    payload: Dict[str, Any] = {"sys_text": f"text {chunk_id}", **payload_extra}
    if doc_id is not None:
        payload["doc_id"] = doc_id
    return SimpleNamespace(id=chunk_id, score=0.5, payload=payload)


class TestIsConcentrated:
    def test_disabled_when_config_switch_off_then_never_triggers(self):
        thresholds = CoverageThresholds(enabled=False)
        assert not is_concentrated(50, 3, 200, thresholds)

    def test_empty_page_when_no_results_then_not_concentrated(self):
        assert not is_concentrated(0, 0, 200, DEFAULTS)

    def test_concentrated_page_when_broad_candidate_pool_then_triggers(self):
        # 50 chunks from 6 docs, 180 candidate docs: the canonical case.
        assert is_concentrated(50, 6, 180, DEFAULTS)

    def test_concentrated_page_when_small_candidate_pool_then_not_triggered(self):
        # Few docs on the page, but the corpus holds barely more: narrow query.
        assert not is_concentrated(50, 6, 10, DEFAULTS)

    def test_distributed_page_when_many_documents_then_not_triggered(self):
        # 30 docs behind 50 chunks is healthy coverage regardless of pool.
        assert not is_concentrated(50, 30, 300, DEFAULTS)

    def test_small_page_when_below_floor_then_floor_applies(self):
        # 10 chunks from 3 docs: fraction gives 1.5 but the floor of 3 keeps
        # small pages eligible when the pool shows breadth.
        assert is_concentrated(10, 3, 9, DEFAULTS)

    def test_ratio_boundary_when_exactly_met_then_triggers(self):
        # candidate_ratio 3.0: 6 docs * 3 = 18 candidates is the boundary.
        assert is_concentrated(50, 6, 18, DEFAULTS)
        assert not is_concentrated(50, 6, 17, DEFAULTS)


class TestCountCandidateDocuments:
    def test_union_when_doc_repeats_across_lists_then_counted_once(self):
        dense = [_point("c1", "doc-a"), _point("c2", "doc-b")]
        sparse = [_point("c3", "doc-a"), _point("c4", "doc-c")]
        assert count_candidate_documents([dense, sparse]) == 3

    def test_missing_doc_id_when_payload_lacks_it_then_skipped(self):
        points = [_point("c1", None), _point("c2", "doc-a")]
        assert count_candidate_documents([points]) == 1

    def test_legacy_field_when_only_sys_doc_id_then_counted(self):
        points = [_point("c1", None, sys_doc_id="doc-z")]
        assert count_candidate_documents([points]) == 1

    def test_none_payload_when_point_has_no_payload_then_skipped(self):
        points = [SimpleNamespace(id="c1", score=0.5, payload=None)]
        assert count_candidate_documents([points]) == 0


class TestRecordCandidateDocuments:
    def test_no_stats_dict_when_caller_opted_out_then_noop(self):
        # Must not raise; nothing to record into.
        _record_candidate_documents(None, [_point("c1", "doc-a")])

    def test_stats_dict_when_provided_then_filled(self):
        stats: Dict[str, int] = {}
        _record_candidate_documents(
            stats, [_point("c1", "doc-a")], [_point("c2", "doc-b")]
        )
        assert stats == {"candidate_documents": 2}


class TestLoadCoverageThresholds:
    def test_missing_config_block_when_absent_then_defaults(self, monkeypatch):
        monkeypatch.setattr(
            coverage_module, "get_application_config", lambda: {"search": {}}
        )
        assert load_coverage_thresholds() == DEFAULTS

    def test_config_block_when_present_then_overrides(self, monkeypatch):
        monkeypatch.setattr(
            coverage_module,
            "get_application_config",
            lambda: {
                "search": {
                    "coverage_alert": {
                        "enabled": False,
                        "max_document_fraction": 0.25,
                        "min_document_floor": 5,
                        "candidate_ratio": 2.0,
                    }
                }
            },
        )
        thresholds = load_coverage_thresholds()
        assert thresholds == CoverageThresholds(
            enabled=False,
            max_document_fraction=0.25,
            min_document_floor=5,
            candidate_ratio=2.0,
        )


def _search_result(chunk_id: str, doc_id: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=f"text {chunk_id}",
        page_num=1,
        headings=[],
        score=0.9,
        title="Doc",
        metadata={},
    )


class TestBuildSearchCoverage:
    def test_scroll_path_when_no_stats_collected_then_none(self):
        assert _build_search_coverage([_search_result("c1", "d1")], None) is None
        assert _build_search_coverage([_search_result("c1", "d1")], {}) is None

    def test_concentrated_results_when_stats_present_then_flagged(self):
        results = [_search_result(f"c{i}", f"d{i % 3}") for i in range(30)]
        coverage = _build_search_coverage(results, {"candidate_documents": 120})
        assert coverage is not None
        assert coverage.chunks_returned == 30
        assert coverage.documents_in_results == 3
        assert coverage.candidate_documents == 120
        assert coverage.concentrated

    def test_distributed_results_when_stats_present_then_not_flagged(self):
        results = [_search_result(f"c{i}", f"d{i}") for i in range(30)]
        coverage = _build_search_coverage(results, {"candidate_documents": 120})
        assert coverage is not None
        assert not coverage.concentrated


class TestMaxChunksPerDocCap:
    def _build(self, points: List[Any], max_chunks_per_doc: int, limit: int = 50):
        doc_ids = {
            str(p.payload.get("doc_id"))
            for p in points
            if p.payload.get("doc_id") is not None
        }
        doc_cache = {d: {"map_title": f"Doc {d}"} for d in doc_ids}
        chunk_cache: Dict[str, Any] = {}
        return _build_search_results(
            points,
            doc_cache,
            chunk_cache,
            "uneg",
            limit,
            0,
            max_chunks_per_doc=max_chunks_per_doc,
        )

    def test_cap_active_when_doc_dominates_then_surplus_chunks_skipped(self):
        points = [_point(f"c{i}", "doc-a") for i in range(5)]
        points += [_point("c5", "doc-b"), _point("c6", "doc-b"), _point("c7", "doc-b")]
        built = self._build(points, max_chunks_per_doc=2)
        per_doc: Dict[str, int] = {}
        for result in built:
            per_doc[result.doc_id] = per_doc.get(result.doc_id, 0) + 1
        assert per_doc == {"doc-a": 2, "doc-b": 2}

    def test_cap_active_when_deeper_pool_then_page_fills_from_more_docs(self):
        # 10 chunks each from doc-a and doc-b, then one chunk each from 8
        # more docs. With limit 12 and a cap of 2 the page must reach them.
        points = [_point(f"a{i}", "doc-a") for i in range(10)]
        points += [_point(f"b{i}", "doc-b") for i in range(10)]
        points += [_point(f"x{i}", f"doc-x{i}") for i in range(8)]
        built = self._build(points, max_chunks_per_doc=2, limit=12)
        assert len(built) == 12
        assert len({r.doc_id for r in built}) == 10

    def test_cap_inactive_when_zero_then_ranking_unchanged(self):
        points = [_point(f"c{i}", "doc-a") for i in range(5)]
        built = self._build(points, max_chunks_per_doc=0)
        assert [r.chunk_id for r in built] == [f"c{i}" for i in range(5)]

    def test_limit_when_cap_active_then_still_respected(self):
        points = [_point(f"c{i}", f"doc-{i}") for i in range(20)]
        built = self._build(points, max_chunks_per_doc=2, limit=10)
        assert len(built) == 10


def _make_request(path: str = "/search") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 1234),
        "app": main_module.app,
    }
    return Request(scope)


def _search_endpoint_kwargs() -> Dict[str, Any]:
    return dict(
        organization=None,
        title=None,
        published_year=None,
        document_type=None,
        country=None,
        language=None,
        dense_weight=None,
        rerank=False,
        recency_boost=False,
        recency_weight=0.15,
        recency_scale_days=365,
        section_types=None,
        keyword_boost_short_queries=True,
        data_source=None,
        min_chunk_size=0,
        model=None,
        rerank_model=None,
        rerank_model_page_size=None,
        auto_min_score=False,
        deduplicate=True,
        field_boost=True,
        field_boost_fields=None,
    )


def _patch_search_stack(monkeypatch, points: List[Any], seen_kwargs: Dict[str, Any]):
    """Wire fake db/pg and a fake search_chunks into the endpoint."""
    db = SimpleNamespace(
        documents_collection="documents",
        chunks_collection="chunks",
        data_source="uneg",
        client=SimpleNamespace(),
    )
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)
    doc_ids = {str(p.payload["doc_id"]) for p in points}
    pg = SimpleNamespace(
        fetch_docs=lambda ids: {d: {"map_title": f"Doc {d}"} for d in doc_ids},
        fetch_chunks=lambda ids: {},
        fetch_indexed_doc_ids=lambda: sorted(doc_ids),
    )
    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: pg)

    def fake_search_chunks(*_args: Any, **kwargs: Any):
        seen_kwargs.update(kwargs)
        coverage_stats = kwargs.get("coverage_stats")
        if coverage_stats is not None:
            coverage_stats["candidate_documents"] = 40
        return points

    monkeypatch.setattr(main_module, "search_chunks", fake_search_chunks)


@pytest.mark.asyncio
async def test_search_endpoint_when_results_concentrated_then_coverage_flagged(
    monkeypatch,
):
    # 10 chunks from 2 documents while 40 documents matched: alert case.
    points = [_point(f"c{i}", f"doc-{i % 2}") for i in range(10)]
    seen_kwargs: Dict[str, Any] = {}
    _patch_search_stack(monkeypatch, points, seen_kwargs)

    result = await main_module.search(
        _make_request(), q="targeting", limit=10, **_search_endpoint_kwargs()
    )

    assert seen_kwargs["limit"] == 10  # no cap: retrieval depth unchanged
    assert result.coverage is not None
    assert result.coverage.chunks_returned == 10
    assert result.coverage.documents_in_results == 2
    assert result.coverage.candidate_documents == 40
    assert result.coverage.concentrated


@pytest.mark.asyncio
async def test_search_endpoint_when_cap_set_then_retrieval_deepened_and_capped(
    monkeypatch,
):
    points = [_point(f"a{i}", "doc-a") for i in range(6)]
    points += [_point(f"b{i}", "doc-b") for i in range(6)]
    points += [_point(f"x{i}", f"doc-x{i}") for i in range(6)]
    seen_kwargs: Dict[str, Any] = {}
    _patch_search_stack(monkeypatch, points, seen_kwargs)

    result = await main_module.search(
        _make_request(),
        q="targeting",
        limit=10,
        max_chunks_per_doc=2,
        **_search_endpoint_kwargs(),
    )

    assert seen_kwargs["limit"] == 40  # limit * BROADEN_FETCH_FACTOR
    per_doc: Dict[str, int] = {}
    for r in result.results:
        per_doc[r.doc_id] = per_doc.get(r.doc_id, 0) + 1
    assert max(per_doc.values()) <= 2
    assert len(result.results) == 10
