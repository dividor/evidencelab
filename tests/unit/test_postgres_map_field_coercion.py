"""Tests for map_field list-to-string coercion in PostgresClientDocs.upsert_doc."""

from unittest.mock import MagicMock, patch

import pytest

from pipeline.db.postgres_client_docs import PostgresDocMixin


@pytest.fixture()
def client():
    """Create a PostgresDocMixin with mocked DB connection."""
    with patch.object(PostgresDocMixin, "__init__", lambda self: None):
        c = PostgresDocMixin.__new__(PostgresDocMixin)
        c.docs_table = "docs_test"
        c.data_source = "test"
        # Stub out column-ensure methods (they normally issue DDL)
        c.ensure_map_doc_columns = MagicMock()
        c.ensure_sys_doc_columns = MagicMock()
        c.ensure_qdrant_legacy_columns = MagicMock()
        c.ensure_sys_doc_taxonomies_column = MagicMock()
        c._extract_status_timestamp = MagicMock(return_value=None)
        c._normalize_timestamp = MagicMock(return_value=None)

        # Mock connection / cursor so we can capture the values list
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        c._get_conn = MagicMock(return_value=mock_conn)
        c._mock_cursor = mock_cursor
        return c


def _call_upsert(client, map_fields):
    """Helper to call upsert_doc with minimal required args."""
    client.upsert_doc(
        doc_id="doc1",
        src_doc_raw_metadata={"raw": "data"},
        map_fields=map_fields,
        sys_summary="summary",
        sys_fields={"sys_status": "scanned"},
    )
    # Return the values list passed to cur.execute
    return client._mock_cursor.execute.call_args[0][1]


class TestMapFieldListCoercion:
    """Verify that list values in map_fields are coerced to '; '-joined strings."""

    def test_list_coerced_to_semicolon_string(self, client):
        values = _call_upsert(client, {"region": ["Africa", "East Asia"]})
        # map_region value should be a joined string, not a list
        assert "Africa; East Asia" in values
        assert ["Africa", "East Asia"] not in values

    def test_single_string_unchanged(self, client):
        values = _call_upsert(client, {"region": "Africa"})
        assert "Africa" in values

    def test_multiple_list_fields(self, client):
        map_fields = {
            "document_type": ["Report", "Brief"],
            "region": ["Africa", "Other"],
            "theme": "Governance",
        }
        values = _call_upsert(client, map_fields)
        assert "Report; Brief" in values
        assert "Africa; Other" in values
        assert "Governance" in values

    def test_empty_list_coerced_to_empty_string(self, client):
        values = _call_upsert(client, {"region": []})
        assert "" in values

    def test_single_item_list_coerced(self, client):
        values = _call_upsert(client, {"region": ["Africa"]})
        assert "Africa" in values
        assert ["Africa"] not in values

    def test_none_value_unchanged(self, client):
        values = _call_upsert(client, {"region": None})
        assert None in values
