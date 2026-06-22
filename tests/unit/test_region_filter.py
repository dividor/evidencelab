"""Unit tests for the region search filter.

Region is a document-level field (it is not stored on chunks), so a region
selection must be resolved to a doc_id filter for chunk search — analogous to
the existing language handling. These tests cover the route-level conversion
and intersection logic plus the Postgres lookup helper.
"""

from unittest.mock import MagicMock

import pytest

from pipeline.db.postgres_client_docs import PostgresDocMixin
from ui.backend.routes.search import (
    _NO_MATCH_DOC_ID,
    _convert_language_to_doc_ids,
    _convert_region_to_doc_ids,
    _intersect_doc_id_filter,
)

pytestmark = pytest.mark.unit


def _pg_returning(doc_ids):
    pg = MagicMock()
    pg.fetch_doc_ids_by_region.return_value = list(doc_ids)
    return pg


class TestConvertRegionToDocIds:
    def test_no_region_when_absent_then_filters_unchanged(self):
        core = {"organization": "WFP"}
        pg = MagicMock()
        _convert_region_to_doc_ids(core, pg)
        assert core == {"organization": "WFP"}
        pg.fetch_doc_ids_by_region.assert_not_called()

    def test_region_when_set_then_replaced_by_doc_id_filter(self):
        core = {"region": "Asia and the Pacific"}
        pg = _pg_returning(["d1", "d2"])
        _convert_region_to_doc_ids(core, pg)
        assert "region" not in core
        assert set(core["doc_id"].split(",")) == {"d1", "d2"}
        pg.fetch_doc_ids_by_region.assert_called_once_with("Asia and the Pacific")

    def test_region_when_no_docs_match_then_sentinel_doc_id(self):
        core = {"region": "Nowhere"}
        _convert_region_to_doc_ids(core, _pg_returning([]))
        assert core["doc_id"] == _NO_MATCH_DOC_ID

    def test_region_and_language_when_both_set_then_doc_ids_intersected(self):
        # Language resolves first (mirrors the call order in the search route).
        core = {"language": "en", "region": "Asia and the Pacific"}
        pg = MagicMock()
        pg.fetch_doc_ids_by_language.return_value = ["d1", "d2", "d3"]
        pg.fetch_doc_ids_by_region.return_value = ["d2", "d3", "d4"]
        _convert_language_to_doc_ids(core, pg)
        _convert_region_to_doc_ids(core, pg)
        assert set(core["doc_id"].split(",")) == {"d2", "d3"}

    def test_region_and_language_when_disjoint_then_sentinel(self):
        core = {"language": "en", "region": "Asia and the Pacific"}
        pg = MagicMock()
        pg.fetch_doc_ids_by_language.return_value = ["d1"]
        pg.fetch_doc_ids_by_region.return_value = ["d9"]
        _convert_language_to_doc_ids(core, pg)
        _convert_region_to_doc_ids(core, pg)
        assert core["doc_id"] == _NO_MATCH_DOC_ID


class TestIntersectDocIdFilter:
    def test_no_existing_doc_id_then_set_directly(self):
        core = {}
        _intersect_doc_id_filter(core, ["a", "b"])
        assert set(core["doc_id"].split(",")) == {"a", "b"}

    def test_existing_doc_id_then_intersection(self):
        core = {"doc_id": "a,b,c"}
        _intersect_doc_id_filter(core, ["b", "c", "d"])
        assert set(core["doc_id"].split(",")) == {"b", "c"}

    def test_empty_new_ids_then_sentinel(self):
        core = {"doc_id": "a,b"}
        _intersect_doc_id_filter(core, [])
        assert core["doc_id"] == _NO_MATCH_DOC_ID


def _make_docs_client(fetch_rows):
    """Build a PostgresDocMixin with a mocked DB connection returning rows."""
    client = PostgresDocMixin.__new__(PostgresDocMixin)
    client.docs_table = "docs_test"
    cursor = MagicMock()
    cursor.fetchall.return_value = fetch_rows
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    conn = MagicMock()
    conn.cursor.return_value = cursor_cm
    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = conn
    client._get_conn = MagicMock(return_value=conn_cm)
    return client, cursor


class TestFetchDocIdsByRegion:
    def test_blank_selection_then_empty_without_query(self):
        client, cursor = _make_docs_client([])
        assert client.fetch_doc_ids_by_region("   ") == []
        cursor.execute.assert_not_called()

    def test_selection_then_returns_doc_ids(self):
        client, cursor = _make_docs_client([("d1",), ("d2",)])
        result = client.fetch_doc_ids_by_region("Asia and the Pacific")
        assert result == ["d1", "d2"]

    def test_selection_then_query_is_parameterized(self):
        client, cursor = _make_docs_client([])
        client.fetch_doc_ids_by_region(
            "Middle East, Northern Africa, and Eastern Europe"
        )
        sql, params = cursor.execute.call_args[0]
        # The user selection must be a bound parameter, never interpolated.
        assert "Middle East" not in sql
        assert params[0] == "Middle East, Northern Africa, and Eastern Europe"
        assert "%s ILIKE" in sql
