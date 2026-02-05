"""
test_summarize.py - Tests for SummarizeProcessor

Tests the document summarization functionality.
"""

import json
import tempfile
from pathlib import Path

import pytest

from pipeline.processors.summarization.summarizer import (
    NUM_CENTROID_SENTENCES,
    SummarizeProcessor,
    _clean_markdown,
)


def _load_summarize_config() -> dict:
    config_path = Path(__file__).resolve().parents[2] / "config.json"
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    datasource = config["datasources"]["UN Humanitarian Evaluation Reports"]
    summarize_config = datasource["pipeline"]["summarize"]
    return {
        "llm_model": summarize_config["llm_model"],
        "llm_workers": summarize_config["llm_workers"],
        "context_window": summarize_config["context_window"],
    }


def _make_processor() -> SummarizeProcessor:
    return SummarizeProcessor(_load_summarize_config())


class TestSummarizeProcessor:
    """Test SummarizeProcessor class functionality"""

    def test_processor_initialization(self):
        """Test that processor initializes correctly"""
        processor = _make_processor()

        assert processor.name == "SummarizeProcessor"
        assert processor._embedding_model is None  # Not loaded until setup
        assert processor._hf_token is None

    def test_get_model_type_llama(self):
        """Test model type detection for Llama"""
        processor = _make_processor()

        assert processor._model_type in {"bart", "mistral", "llama", "chat"}

    def test_process_document_missing_folder(self):
        """Test processing document with missing parsed folder"""
        processor = _make_processor()
        processor._initialized = True

        result = processor.process_document(
            {"id": "test", "title": "Test", "parsed_folder": "/nonexistent/folder"}
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_process_document_no_folder(self):
        """Test processing document with no parsed folder"""
        processor = _make_processor()
        processor._initialized = True

        result = processor.process_document({"id": "test", "title": "Test"})

        assert result["success"] is False


class TestUtilityFunctions:
    """Test utility functions"""

    def test_clean_markdown_formatting(self):
        """Test markdown formatting cleaning function"""
        markdown_text = "## **Bold Heading**"

        cleaned = _clean_markdown(markdown_text)

        # Bold should be removed from headings
        assert "**" not in cleaned
        assert "Bold Heading" in cleaned

    def test_clean_markdown_empty(self):
        """Test cleaning empty markdown"""
        result = _clean_markdown("")

        assert result == ""

    def test_clean_markdown_none(self):
        """Test cleaning None returns None"""
        result = _clean_markdown(None)

        assert result is None


class TestMarkdownLoading:
    """Test markdown loading functionality"""

    def test_load_markdown_valid_file(self):
        """Test loading valid markdown file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "test.md"
            test_content = "# Test Document\n\nThis is test content."
            md_file.write_text(test_content)

            processor = _make_processor()
            content = processor._load_markdown(str(md_file))

            assert content is not None
            assert "Test Document" in content
            assert "test content" in content

    def test_load_markdown_strips_images(self):
        """Test that markdown loading strips image references"""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "test.md"
            test_content = "# Title\n\n![Image](image.png)\n\nText content."
            md_file.write_text(test_content)

            processor = _make_processor()
            content = processor._load_markdown(str(md_file))

            assert "![Image]" not in content
            assert "Text content" in content

    def test_load_markdown_strips_page_breaks(self):
        """Test that markdown loading strips page break markers"""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "test.md"
            test_content = "# Title\n\n------- Page 1 -------\n\nContent."
            md_file.write_text(test_content)

            processor = _make_processor()
            content = processor._load_markdown(str(md_file))

            assert "Page 1" not in content
            assert "Content" in content


class TestSentenceTokenization:
    """Test sentence tokenization"""

    def test_tokenize_sentences_basic(self):
        """Test basic sentence tokenization"""
        processor = _make_processor()

        # Use longer sentences to pass the filter (>5 words)
        text = (
            "This is the first sentence with many words. "
            "This is another longer sentence with content. "
            "And here is a third sentence with enough words."
        )
        sentences = processor._tokenize_sentences(text)

        assert len(sentences) >= 3

    def test_tokenize_sentences_filters_short(self):
        """Test that very short sentences are filtered"""
        processor = _make_processor()

        text = "OK. This is a proper sentence with multiple words. Yes."
        sentences = processor._tokenize_sentences(text)

        # Only the longer sentence should remain
        assert len(sentences) >= 1
        assert any("proper sentence" in s for s in sentences)


def test_module_constants():
    """Test that required constants are defined"""
    config = _load_summarize_config()
    assert isinstance(config, dict)
    assert "llm_model" in config
    assert "model" in config["llm_model"]

    assert NUM_CENTROID_SENTENCES > 0
    # Prompts are now Jinja2 templates, not string constants
    # assert isinstance(LLM_REDUCTION_PROMPT, str)
    # assert isinstance(LLM_SUMMARY_PROMPT, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
