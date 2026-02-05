import os
import sys
import unittest
from unittest.mock import patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from pipeline.orchestrator.worker import init_worker  # noqa: E402


class TestOrchestratorConfig(unittest.TestCase):
    @patch("pipeline.orchestrator.worker.get_db")
    @patch("pipeline.orchestrator.worker.RemoteEmbeddingClient")
    @patch("pipeline.orchestrator.worker.SummarizeProcessor")
    def test_init_worker_propagates_llm_config(
        self, mock_summarizer_cls, mock_remote_client, mock_get_db
    ):
        """
        Test that init_worker correctly extracts LLM config from pipeline_config
        or global config.
        """

        # 1. Test Fallback Case: No LLM in pipeline_config
        pipeline_config = {"summarize": {"temperature": 0.7}}

        # Run init_worker
        # We need OS env for EMBEDDING_API_URL to trigger RemoteEmbeddingClient pathway or not
        with patch.dict(os.environ, {"EMBEDDING_API_URL": "http://localhost:9999"}):
            init_worker(
                data_source="test_source",
                skip_parse=True,
                skip_summarize=False,  # We want to test summarizer init
                skip_index=True,
                skip_tag=True,
                pipeline_config=pipeline_config,
            )

        # Verify SummarizeProcessor was initialized with summarize config
        mock_summarizer_cls.assert_called()
        call_args = mock_summarizer_cls.call_args[1]  # keyword args

        self.assertEqual(call_args["config"], pipeline_config["summarize"])

        # 2. Test Explicit Case: LLM in pipeline_config
        mock_summarizer_cls.reset_mock()
        pipeline_config_explicit = {
            "summarize": {"llm_model": "explicit-model-8b", "chunk_overlap": 500}
        }

        with patch.dict(os.environ, {"EMBEDDING_API_URL": "http://localhost:9999"}):
            init_worker(
                data_source="test_source",
                skip_parse=True,
                skip_summarize=False,
                skip_index=True,
                skip_tag=True,
                pipeline_config=pipeline_config_explicit,
            )

        call_args = mock_summarizer_cls.call_args[1]
        self.assertEqual(call_args["config"]["llm_model"], "explicit-model-8b")
        self.assertEqual(call_args["config"]["chunk_overlap"], 500)


if __name__ == "__main__":
    unittest.main()
