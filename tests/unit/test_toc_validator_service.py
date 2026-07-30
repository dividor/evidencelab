"""Unit tests for the TOC validator backend service."""

from unittest.mock import MagicMock

import pytest

from pipeline.validation.section_inclusion import INTRO_RANGE_FIELD
from ui.backend.services import toc_validator as service

pytestmark = pytest.mark.unit


def _doc(toc, page_range):
    return {
        "sys_status": "indexed",
        "sys_data": {"sys_toc_classified": toc},
        "src_doc_raw_metadata": {INTRO_RANGE_FIELD: page_range},
        "map_title": "Doc",
    }


class TestRunValidation:
    def test_run_validation_persists_and_returns_results(self):
        pg = MagicMock()
        pg.fetch_docs.return_value = {
            "d1": _doc("[H1] Misfiled | annexes | page 40", "(13, 67)"),
        }
        results = service.run_validation(
            pg, ["d1"], validated_by="admin@x.io", validated_at="2026-01-01T00:00:00Z"
        )
        assert len(results) == 1
        row = results[0]
        assert row["doc_id"] == "d1"
        assert row["status"] == "fail"
        assert row["excluded_section_types"] == ["annexes"]
        assert row["validated_by"] == "admin@x.io"
        assert row["validated_at"] == "2026-01-01T00:00:00Z"

        # Persisted via merge_doc_sys_fields under the sys_toc_validation field.
        pg.merge_doc_sys_fields.assert_called_once()
        _, kwargs = pg.merge_doc_sys_fields.call_args
        assert kwargs["doc_id"] == "d1"
        assert kwargs["sys_fields"][service.SYS_FIELD]["status"] == "fail"

    def test_run_validation_skips_unknown_doc_ids(self):
        pg = MagicMock()
        pg.fetch_docs.return_value = {}
        results = service.run_validation(pg, ["missing"], validated_by=None)
        assert results == []
        pg.merge_doc_sys_fields.assert_not_called()

    def test_run_validation_stamps_when_no_timestamp_given(self):
        pg = MagicMock()
        pg.fetch_docs.return_value = {
            "d1": _doc("[H1] F | findings | page 30", "(13, 67)")
        }
        results = service.run_validation(pg, ["d1"])
        assert results[0]["status"] == "pass"
        assert results[0]["validated_at"]  # non-empty ISO timestamp

    def test_run_validation_preserves_requested_order(self):
        pg = MagicMock()
        pg.fetch_docs.return_value = {
            "a": _doc("[H1] F | findings | page 30", "(13, 67)"),
            "b": _doc("[H1] X | annexes | page 40", "(13, 67)"),
        }
        results = service.run_validation(pg, ["b", "a"])
        assert [r["doc_id"] for r in results] == ["b", "a"]


class TestGetStoredResults:
    def test_get_stored_results_returns_only_validated(self):
        pg = MagicMock()
        pg.fetch_doc_sys_fields.return_value = {
            "d1": {"sys_toc_validation": {"status": "fail"}},
            "d2": {"sys_status": "indexed"},  # never validated
        }
        results = service.get_stored_results(pg)
        assert list(results.keys()) == ["d1"]
        assert results["d1"]["status"] == "fail"

    def test_get_stored_results_when_none_then_empty(self):
        pg = MagicMock()
        pg.fetch_doc_sys_fields.return_value = {}
        assert service.get_stored_results(pg) == {}
