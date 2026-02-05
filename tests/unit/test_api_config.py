import os
import sys
import unittest
from unittest.mock import patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# We need to mock DB_VECTORS before importing search
# But search imports DB_VECTORS from pipeline.db
# So we need to ensure pipeline.db is mocked or configured before search is imported.
# However, pipeline.db code runs at import time.


class TestApiConfig(unittest.TestCase):
    @patch("pipeline.db.json.load")
    @patch("pipeline.db.Path.exists")  # We need to mock existence check too
    @patch("pipeline.db.open")  # And open
    def test_search_config_loads_defaults(self, mock_open, mock_exists, mock_json_load):
        """Test that search module loads default model configuration correctly."""
        # Setup mock config
        mock_config = {
            "application": {
                "search": {"default_dense_model": "test-model-v1", "dense_weight": 0.5}
            },
            "supported_embedding_models": {
                "test-model-v1": {
                    "type": "dense",
                    "size": 128,
                    "model_id": "mock/test-model-v1",
                }
            },
        }
        mock_json_load.return_value = mock_config
        mock_exists.return_value = True  # config.json exists

        # We need to reload pipeline.db to pick up the mock config
        import importlib

        import pipeline.db

        importlib.reload(pipeline.db)

        # Now import search
        import ui.backend.services.search

        importlib.reload(ui.backend.services.search)

        # Verify DENSE_VECTOR_NAME is set from config
        self.assertEqual(pipeline.db.DENSE_VECTOR_NAME, "test-model-v1")

        # Verify DB_VECTORS is populated
        self.assertIn("test-model-v1", pipeline.db.DB_VECTORS)

    @patch("pipeline.db.json.load")
    @patch("pipeline.db.Path.exists")
    @patch("pipeline.db.open")
    def test_search_config_handles_missing_defaults(
        self, mock_open, mock_exists, mock_json_load
    ):
        """Test fallback when defaults are not specified."""
        mock_config = {
            "application": {"search": {}},  # No default_dense_model
            "supported_embedding_models": {
                "e5_large": {
                    "type": "dense",
                    "size": 1024,
                    "model_id": "intfloat/multilingual-e5-large",
                }
            },
        }
        mock_json_load.return_value = mock_config
        mock_exists.return_value = True

        import importlib

        import pipeline.db

        importlib.reload(pipeline.db)

        # Expect fallback to "e5_large" as defined in pipeline/db.py line 151
        self.assertEqual(pipeline.db.DENSE_VECTOR_NAME, "e5_large")


if __name__ == "__main__":
    unittest.main()
