"""Tests for Database.create_payload_indexes — src_* field indexing from config."""

from unittest.mock import MagicMock, patch


def _make_db_instance(data_source="uneg"):
    """Build a Database-like object without connecting to Qdrant/Postgres."""
    from pipeline.db.database import Database

    # Bypass __init__ entirely — we only care about create_payload_indexes
    instance = object.__new__(Database)
    instance.data_source = data_source
    instance.documents_collection = f"documents_{data_source}"
    instance.chunks_collection = f"chunks_{data_source}"
    instance.client = MagicMock()
    return instance


class TestCreatePayloadIndexesSrcFields:
    """Verify that create_payload_indexes reads src_* from config and indexes them."""

    def test_src_field_from_config_is_indexed(self):
        db = _make_db_instance()
        ds_config = {
            "default_filter_fields": {"src_geographic_scope": "Geographic Scope"},
            "pipeline": {},
        }
        with patch.object(db, "_load_datasource_config", return_value=ds_config):
            db.create_payload_indexes()

        # Gather all field names that were indexed on the documents collection
        indexed_fields = [
            c.kwargs["field_name"]
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.documents_collection
        ]
        assert "src_geographic_scope" in indexed_fields

    def test_multiple_src_fields_indexed(self):
        db = _make_db_instance()
        ds_config = {
            "default_filter_fields": {
                "src_geographic_scope": "Geographic Scope",
                "src_budget": "Budget",
                "organization": "Organization",  # non-src, should be skipped
            },
            "pipeline": {},
        }
        with patch.object(db, "_load_datasource_config", return_value=ds_config):
            db.create_payload_indexes()

        indexed_fields = [
            c.kwargs["field_name"]
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.documents_collection
        ]
        assert "src_geographic_scope" in indexed_fields
        assert "src_budget" in indexed_fields

    def test_non_src_filter_fields_not_added(self):
        db = _make_db_instance()
        ds_config = {
            "default_filter_fields": {
                "organization": "Organization",
                "country": "Country",
            },
            "pipeline": {},
        }
        with patch.object(db, "_load_datasource_config", return_value=ds_config):
            db.create_payload_indexes()

        indexed_fields = [
            c.kwargs["field_name"]
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.documents_collection
        ]
        # These are non-src fields, so they should NOT appear beyond the hardcoded
        # map_* entries already in the method
        assert "organization" not in indexed_fields
        assert "country" not in indexed_fields

    def test_hardcoded_map_fields_always_present(self):
        db = _make_db_instance()
        ds_config = {"default_filter_fields": {}, "pipeline": {}}
        with patch.object(db, "_load_datasource_config", return_value=ds_config):
            db.create_payload_indexes()

        indexed_fields = [
            c.kwargs["field_name"]
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.documents_collection
        ]
        assert "map_organization" in indexed_fields
        assert "map_country" in indexed_fields
        assert "map_published_year" in indexed_fields

    def test_src_field_not_duplicated_if_already_hardcoded(self):
        """If a src_* field were somehow in the hardcoded list, don't double-index."""
        db = _make_db_instance()
        ds_config = {
            "default_filter_fields": {"src_geographic_scope": "Geographic Scope"},
            "pipeline": {},
        }
        with patch.object(db, "_load_datasource_config", return_value=ds_config):
            db.create_payload_indexes()

        # Count how many times src_geographic_scope appears for documents collection
        count = sum(
            1
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.documents_collection
            and c.kwargs.get("field_name") == "src_geographic_scope"
        )
        assert count == 1

    def test_taxonomy_tag_fields_still_indexed(self):
        db = _make_db_instance()
        ds_config = {
            "default_filter_fields": {"src_geographic_scope": "Geographic Scope"},
            "pipeline": {"tag": {"taxonomies": {"sdg": {"labels": []}}}},
        }
        with patch.object(db, "_load_datasource_config", return_value=ds_config):
            db.create_payload_indexes()

        indexed_fields = [
            c.kwargs["field_name"]
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.documents_collection
        ]
        assert "tag_sdg" in indexed_fields
        assert "src_geographic_scope" in indexed_fields

    def test_empty_config_still_works(self):
        db = _make_db_instance()
        ds_config = {}  # No filter_fields, no pipeline
        with patch.object(db, "_load_datasource_config", return_value=ds_config):
            db.create_payload_indexes()

        # Should still index the hardcoded fields without errors
        indexed_fields = [
            c.kwargs["field_name"]
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.documents_collection
        ]
        assert "map_organization" in indexed_fields

    def test_src_field_indexed_on_both_collections(self):
        """src_* fields should be indexed on both documents and chunks."""
        db = _make_db_instance()
        ds_config = {
            "default_filter_fields": {"src_geographic_scope": "Geographic Scope"},
            "pipeline": {},
        }
        with patch.object(db, "_load_datasource_config", return_value=ds_config):
            db.create_payload_indexes()

        docs_fields = [
            c.kwargs["field_name"]
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.documents_collection
        ]
        chunks_fields = [
            c.kwargs["field_name"]
            for c in db.client.create_payload_index.call_args_list
            if c.kwargs.get("collection_name") == db.chunks_collection
        ]
        assert "src_geographic_scope" in docs_fields
        assert "src_geographic_scope" in chunks_fields
