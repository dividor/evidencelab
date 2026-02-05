"""
Tests for data source isolation feature.

Verifies that:
1. Different data sources get separate collections
2. Database instances are isolated
3. Collection names are correctly generated
"""

from unittest.mock import Mock, patch


# Helper to mock both Qdrant and Postgres clients
def _db_mocks():
    """Return patch objects for mocking database clients."""
    return (
        patch("pipeline.db.QdrantClient"),
        patch("pipeline.db.database.PostgresClient"),
    )


class TestDataSourceIsolation:
    """Test data source isolation in the database layer."""

    def test_collection_names_include_data_source(self):
        """Verify collection names are generated from data source."""
        from pipeline.db import Database

        # Mock both Qdrant and Postgres clients to avoid actual connections
        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            mock_qdrant.return_value.get_collections.return_value.collections = []

            db = Database(data_source="test_source")

            assert db.documents_collection == "documents_test_source"
            assert db.chunks_collection == "chunks_test_source"
            assert db.data_source == "test_source"

    def test_default_data_source(self):
        """Verify default data source is used when none specified."""
        from pipeline.db import DEFAULT_DATA_SOURCE, Database

        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            mock_qdrant.return_value.get_collections.return_value.collections = []

            db = Database()  # No data_source specified

            assert db.data_source == DEFAULT_DATA_SOURCE
            assert db.documents_collection == f"documents_{DEFAULT_DATA_SOURCE}"
            assert db.chunks_collection == f"chunks_{DEFAULT_DATA_SOURCE}"

    def test_different_data_sources_different_collections(self):
        """Verify different data sources create different collection names."""
        from pipeline.db import Database

        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            mock_qdrant.return_value.get_collections.return_value.collections = []

            db_uneg = Database(data_source="uneg")
            db_gcf = Database(data_source="gcf")

            # Collections should be different
            assert db_uneg.documents_collection != db_gcf.documents_collection
            assert db_uneg.chunks_collection != db_gcf.chunks_collection

            # But follow consistent naming pattern
            assert db_uneg.documents_collection == "documents_uneg"
            assert db_gcf.documents_collection == "documents_gcf"

    def test_get_db_factory_function(self):
        """Verify get_db factory creates correct instances."""
        from pipeline.db import get_db

        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            mock_qdrant.return_value.get_collections.return_value.collections = []

            db1 = get_db("source_a")
            db2 = get_db("source_b")

            assert db1.data_source == "source_a"
            assert db2.data_source == "source_b"
            assert db1.documents_collection != db2.documents_collection


class TestProcessorDataSourceIntegration:
    """Test that processors correctly use data source."""

    def test_scanner_accepts_db_parameter(self):
        """Verify ScanProcessor accepts db parameter."""
        from pipeline.db import Database
        from pipeline.processors.scanning.scanner import ScanProcessor

        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            mock_qdrant.return_value.get_collections.return_value.collections = []

            custom_db = Database(data_source="custom")
            scanner = ScanProcessor(base_dir="./test", db=custom_db)

            assert scanner.db.data_source == "custom"
            assert scanner.db.documents_collection == "documents_custom"

    def test_indexer_accepts_db_parameter(self):
        """Verify IndexProcessor accepts db parameter."""
        from pipeline.db import Database
        from pipeline.processors.indexing.indexer import IndexProcessor

        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            mock_qdrant.return_value.get_collections.return_value.collections = []

            custom_db = Database(data_source="custom")
            indexer = IndexProcessor(db=custom_db)

            assert indexer.db.data_source == "custom"
            assert indexer.db.chunks_collection == "chunks_custom"


class TestSearchDataSourceIntegration:
    """Test that search correctly uses data source."""

    def test_search_chunks_uses_correct_collection(self):
        """Verify search_chunks uses the db's collection name."""
        import numpy as np

        from pipeline.db import Database
        from ui.backend.services.search import search_chunks

        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            # Setup mock
            mock_qdrant.return_value.get_collections.return_value.collections = []
            # Mock query_points to return empty results (current API uses query_points, not search)
            mock_query_response = Mock()
            mock_query_response.points = []
            mock_qdrant.return_value.query_points.return_value = mock_query_response

            custom_db = Database(data_source="test_search")

            # Mock the embedding models with numpy arrays (like real models return)
            with patch(
                "ui.backend.services.search.get_dense_model"
            ) as mock_dense_model, patch(
                "ui.backend.services.search.get_sparse_model"
            ) as mock_sparse_model:
                mock_dense = Mock()
                mock_sparse = Mock()
                # Return numpy array like real embedding model
                mock_dense.embed.return_value = iter([np.array([0.1] * 384)])
                sparse_result = Mock()
                sparse_result.indices = np.array([1, 2])
                sparse_result.values = np.array([0.5, 0.3])
                mock_sparse.embed.return_value = iter([sparse_result])
                mock_dense_model.return_value = mock_dense
                mock_sparse_model.return_value = mock_sparse

                # Call search with custom db (use dense_weight=1.0 for simpler test path)
                search_chunks("test query", limit=10, dense_weight=1.0, db=custom_db)

                # Verify query_points was called with correct collection
                calls = mock_qdrant.return_value.query_points.call_args_list
                assert len(calls) > 0
                # Check that collection_name matches our custom db
                assert calls[0].kwargs.get("collection_name") == "chunks_test_search"


class TestDatabaseCountMethods:
    """Test count methods use correct collections."""

    def test_count_documents_uses_correct_collection(self):
        """Verify count_documents uses the data source's collection."""
        from pipeline.db import Database

        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            mock_qdrant.return_value.get_collections.return_value.collections = []
            mock_qdrant.return_value.count.return_value = Mock(count=42)

            db = Database(data_source="count_test")
            count = db.count_documents()

            # Verify count was called with correct collection
            mock_qdrant.return_value.count.assert_called_with(
                collection_name="documents_count_test"
            )
            assert count == 42

    def test_count_chunks_uses_correct_collection(self):
        """Verify count_chunks uses the data source's collection."""
        from pipeline.db import Database

        with patch("pipeline.db.QdrantClient") as mock_qdrant, patch(
            "pipeline.db.database.PostgresClient"
        ):
            mock_qdrant.return_value.get_collections.return_value.collections = []
            mock_qdrant.return_value.count.return_value = Mock(count=100)

            db = Database(data_source="count_test")
            count = db.count_chunks()

            # Verify count was called with correct collection
            args, kwargs = mock_qdrant.return_value.count.call_args
            assert kwargs.get("collection_name") == "chunks_count_test"
            assert kwargs.get("count_filter") is None
            assert count == 100
