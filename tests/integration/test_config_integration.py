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

        # We need a shared embedding model mock to avoid instantiating the heavy one
        # BUT orchestrator creates it if we don't pass it?
        # init_worker doesn't take embedding_model arg, it expects global shared_dense_model
        # We need to mock shared_dense_model module-level variable in orchestrator IF we can
        # OR just let it try to load.
        # Loading "e5_large" locally takes time/memory.
        # But wait, init_worker uses `shared_dense_model` from `orchestrator.py`?

        # Let's check init_worker signature:
        # def init_worker(data_source, skip_parse, skip_summarize, skip_index,
        #                 skip_tag, pipeline_config=None, shared_objects=None):
        # It takes `shared_objects`? No, checking code...
        # It uses global variables.

        # We should patch the embedding model instantiation in orchestrator to avoid heavy lift
        # but let the config logic run real.

        from unittest.mock import patch

        # We need to patch where the classes are DEFINED or IMPORTED.
        # orchestrator imports RemoteEmbeddingClient from pipeline.utilities.embedding_client
        # it imports TextEmbedding inside the function from fastembed

        with patch("pipeline.utilities.embedding_client.RemoteEmbeddingClient"), patch(
            "fastembed.TextEmbedding"
        ), patch("pipeline.db.Database.init_collections"), patch(
            "pipeline.db.Database.create_payload_indexes"
        ):

            # We also need to mock SentenceTransformer if used somewhere,
            # but orchestrator doesn't seem to use it directly in init_worker locally?
            # It uses TextEmbedding or RemoteEmbeddingClient.

            # Force pipeline_config to be empty to trigger fallback
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
