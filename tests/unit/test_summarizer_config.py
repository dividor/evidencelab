import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from pipeline.processors.summarization.summarizer import (  # noqa: E402
    SummarizeProcessor,
)


class TestSummarizerConfig(unittest.TestCase):
    def setUp(self):
        self.mock_llm_config = {
            "model": "meta-llama/Llama-3.2-3B-Instruct",
            "provider": "novita",
            "max_tokens": 500,
            "temperature": 0.2,
        }

    @patch("utils.llm_factory.get_llm")
    def test_summarizer_passes_explicit_config(self, mock_get_llm):
        """Test that SummarizeProcessor passes its configured model to get_llm."""
        # Setup mock to return a dummy LLM object
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        # Setup response with .content attribute
        mock_response = MagicMock()
        mock_response.content = (
            "This is a valid summary that is definitely longer than twenty characters."
        )
        mock_llm.invoke.return_value = mock_response

        # Initialize processor with explicit config
        processor = SummarizeProcessor(
            config={"llm_model": {**self.mock_llm_config, "temperature": 0.1}}
        )

        # We need to mock _embedding_model and _hf_token to pass setup()/ensure_setup()
        processor._embedding_model = MagicMock()
        processor._hf_token = "fake_token"

        # Call the internal method that triggers get_llm
        content = "Test content " * 10
        result = processor._llm_summary(content)

        # Assert result is the content string (first element of tuple)
        summary, meta = result
        self.assertEqual(
            summary,
            "This is a valid summary that is definitely longer than twenty characters.",
        )

        # Assert get_llm was called with the specific model config
        mock_get_llm.assert_called_with(
            model="meta-llama/Llama-3.2-3B-Instruct",
            provider="novita",
            max_tokens=500,
            temperature=0.1,
            inference_provider=None,
        )

    @patch("utils.llm_factory.get_llm")
    def test_llm_summary_calls_factory_correctly(self, mock_get_llm):
        """Verify _llm_summary calls get_llm with the correct arguments."""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        # Setup response with .content attribute
        mock_response = MagicMock()
        mock_response.content = (
            "This is a valid summary that is definitely longer than twenty characters."
        )
        mock_llm.invoke.return_value = mock_response

        processor = SummarizeProcessor(
            config={"llm_model": {**self.mock_llm_config, "temperature": 0.1}}
        )
        processor._embedding_model = MagicMock()
        processor._hf_token = "fake_token"

        # Call internal method
        content = "This is a test document content " * 100  # Make it long enough
        processor._llm_summary(content)

        # Assert get_llm was called with specific args from config
        mock_get_llm.assert_called_with(
            model="meta-llama/Llama-3.2-3B-Instruct",
            provider="novita",
            max_tokens=500,
            temperature=0.1,
            inference_provider=None,
        )


if __name__ == "__main__":
    unittest.main()
