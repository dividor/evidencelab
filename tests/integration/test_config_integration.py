import os
import shutil  # noqa: F401
import sys
import unittest

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import pipeline.db  # noqa: E402
from pipeline.db import load_datasources_config  # noqa: E402
from pipeline.orchestrator import init_worker  # noqa: E402


class TestConfigIntegration(unittest.TestCase):
    def setUp(self):
        # Ensure we are testing with specific config
        self.original_config = pipeline.db._datasources_config
        pipeline.db._datasources_config = {}  # Force reload

    def tearDown(self):
        pipeline.db._datasources_config = self.original_config

    def test_init_worker_loads_real_config(self):
        """Test that init_worker loads configuration from the actual file system without mocks."""

        # We assume the config.json in the repo root is valid and has "ai_summary" enabled.
        # If not, we might fail, but that's what we want to know.

        # Override environment to ensure no env var interference (though code should ignore it)
        os.environ["EMBEDDING_API_URL"] = "http://localhost:5001"

        # Load real pipeline config for the data source
        config = load_datasources_config()
        source_config = config.get("datasources", {}).get(
            "UN Humanitarian Evaluation Reports", {}
        )
        pipeline_config = source_config.get("pipeline", {})

        # Patch EmbeddingService to avoid heavy model loading while letting
        # config logic run for real.

        from unittest.mock import MagicMock, patch

        # Patch EmbeddingService to avoid heavy model loading
        mock_embedding_service = MagicMock()

        with patch(
            "pipeline.orchestrator.worker.EmbeddingService",
            return_value=mock_embedding_service,
        ), patch("pipeline.db.Database.init_collections"), patch(
            "pipeline.db.Database.create_payload_indexes"
        ):

            init_worker(
                data_source="uneg",  # Use 'uneg' so get_db can find config
                skip_parse=True,
                skip_summarize=False,
                skip_index=True,
                skip_tag=True,
                pipeline_config=pipeline_config,
            )

        # Retrieve initialized summarizer
        # MUST access via module to get the updated global variable, not the imported reference
        import pipeline.orchestrator

        summarizer = pipeline.orchestrator._worker_context.get("summarizer")

        if not summarizer:
            self.fail("Summarizer was not initialized!")

        print(f"\nDEBUG: Summarizer model key: {summarizer.model_key}")

        # Verify Fallback worked
        self.assertIsNotNone(summarizer.model_key)
        print(f"DEBUG: Model found: {summarizer.model_key}")

        # Check if it matches what's in config.json (allow Qwen or global-model)
        self.assertTrue(
            summarizer.model_key.startswith("Qwen/")
            or summarizer.model_key.startswith("meta-llama/")
            or summarizer.model_key.startswith("global-model")
        )


if __name__ == "__main__":
    unittest.main()
