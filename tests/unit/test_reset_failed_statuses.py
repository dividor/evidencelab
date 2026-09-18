"""Unit tests for the document status reset script.

Covers which statuses are reset, the opt-in classes of stuck work, and the
guarantee that a dry run touches nothing.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "pipeline"
    / "reset_failed_statuses.py"
)
_spec = importlib.util.spec_from_file_location("reset_failed_statuses", _SCRIPT_PATH)
rfs = importlib.util.module_from_spec(_spec)
sys.modules["reset_failed_statuses"] = rfs
_spec.loader.exec_module(rfs)


def _make_db(by_status=None, empty_indexed=None):
    """A Database stand-in whose pg mixin answers from the given maps."""
    by_status = by_status or {}
    db = MagicMock()
    db.pg.fetch_docs_by_status.side_effect = lambda status, **_: [
        {"id": doc_id} for doc_id in by_status.get(status, [])
    ]
    db.pg.fetch_doc_ids_indexed_without_chunks.return_value = list(empty_indexed or [])
    return db


def _reset_ids(db):
    return [call.kwargs["doc_id"] for call in db.pg.merge_doc_sys_fields.call_args_list]


@pytest.mark.unit
def test_reset_when_documents_failed_then_marked_downloaded():
    db = _make_db({"index_failed": ["a"], "parse_failed": ["b"]})
    with patch.object(rfs, "Database", return_value=db):
        rfs.reset_failed_statuses(data_source="uneg")

    assert sorted(_reset_ids(db)) == ["a", "b"]
    fields = db.pg.merge_doc_sys_fields.call_args_list[0].kwargs["sys_fields"]
    assert fields["sys_status"] == "downloaded"
    assert fields["sys_error_message"] is None


@pytest.mark.unit
def test_reset_when_stuck_not_requested_then_mid_stage_left_alone():
    db = _make_db({"index_failed": ["a"], "indexing": ["stuck"]})
    with patch.object(rfs, "Database", return_value=db):
        rfs.reset_failed_statuses(data_source="uneg")

    assert _reset_ids(db) == ["a"]
    queried = {c.kwargs["status"] for c in db.pg.fetch_docs_by_status.call_args_list}
    assert "indexing" not in queried


@pytest.mark.unit
def test_reset_when_include_stuck_then_mid_stage_documents_reset():
    db = _make_db({"indexing": ["i"], "parsing": ["p"], "tagging": ["t"]})
    with patch.object(rfs, "Database", return_value=db):
        rfs.reset_failed_statuses(data_source="uneg", include_stuck=True)

    assert sorted(_reset_ids(db)) == ["i", "p", "t"]


@pytest.mark.unit
def test_reset_when_include_empty_indexed_then_chunkless_documents_reset():
    db = _make_db(empty_indexed=["ghost"])
    with patch.object(rfs, "Database", return_value=db):
        rfs.reset_failed_statuses(data_source="uneg", include_empty_indexed=True)

    assert _reset_ids(db) == ["ghost"]


@pytest.mark.unit
def test_reset_when_empty_indexed_not_requested_then_not_queried():
    db = _make_db(empty_indexed=["ghost"])
    with patch.object(rfs, "Database", return_value=db):
        rfs.reset_failed_statuses(data_source="uneg")

    db.pg.fetch_doc_ids_indexed_without_chunks.assert_not_called()
    assert _reset_ids(db) == []


@pytest.mark.unit
def test_reset_when_dry_run_then_nothing_is_written():
    db = _make_db({"index_failed": ["a"]}, empty_indexed=["ghost"])
    with patch.object(rfs, "Database", return_value=db):
        rfs.reset_failed_statuses(
            data_source="uneg",
            dry_run=True,
            include_stuck=True,
            include_empty_indexed=True,
        )

    db.pg.merge_doc_sys_fields.assert_not_called()


@pytest.mark.unit
def test_reset_when_database_errors_then_it_propagates():
    db = _make_db()
    db.pg.fetch_docs_by_status.side_effect = RuntimeError("connection lost")
    with patch.object(rfs, "Database", return_value=db):
        with pytest.raises(RuntimeError, match="connection lost"):
            rfs.reset_failed_statuses(data_source="uneg")
