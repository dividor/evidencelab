"""Tests for scripts/pipeline/prepare_reindex.py (re-index a restored data source)."""

from unittest.mock import MagicMock

import pytest

from scripts.pipeline import prepare_reindex as pr

pytestmark = pytest.mark.unit


def _database(docs):
    db = MagicMock()
    db.documents_collection = "documents_wfp"
    db.chunks_collection = "chunks_wfp"
    db.pg.fetch_docs_by_status.return_value = docs
    factory = MagicMock(return_value=db)
    return factory, db


class TestPrepareReindex:
    def test_prepare_reindex_when_dry_run_then_counts_and_changes_nothing(self):
        factory, db = _database([{"id": "a"}, {"id": "b"}])
        assert pr.prepare_reindex("wfp", dry_run=True, database=factory) == 2
        factory.assert_called_once_with(data_source="wfp")
        db.pg.fetch_docs_by_status.assert_called_once_with(status="indexed")
        db.clear_all_data.assert_not_called()
        db.pg.merge_doc_sys_fields.assert_not_called()

    def test_prepare_reindex_when_run_then_index_emptied_and_docs_marked_tagged(self):
        factory, db = _database([{"id": "a"}, {"id": 7}])
        assert pr.prepare_reindex("wfp", database=factory) == 2
        db.clear_all_data.assert_called_once_with()
        marked = [
            (c.kwargs["doc_id"], c.kwargs["sys_fields"]["sys_status"])
            for c in db.pg.merge_doc_sys_fields.call_args_list
        ]
        assert marked == [("a", "tagged"), ("7", "tagged")]
        assert all(
            "sys_last_updated" in c.kwargs["sys_fields"]
            for c in db.pg.merge_doc_sys_fields.call_args_list
        )

    def test_prepare_reindex_when_no_indexed_docs_then_index_still_emptied(self):
        factory, db = _database([])
        assert pr.prepare_reindex("wfp", database=factory) == 0
        db.clear_all_data.assert_called_once_with()
        db.pg.merge_doc_sys_fields.assert_not_called()
