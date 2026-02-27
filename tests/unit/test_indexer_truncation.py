"""
Unit tests for IndexProcessor chunk truncation and max_embed_chars computation.

Tests cover:
- _compute_max_embed_chars: config-driven character limit derivation
- _filter_valid_chunks: empty-chunk filtering and oversized-chunk truncation
"""

from unittest.mock import patch

from pipeline.processors.indexing.indexer import (
    _CHARS_PER_TOKEN,
    _DEFAULT_MAX_EMBED_TOKENS,
    IndexProcessor,
)


class TestComputeMaxEmbedChars:
    """Test _compute_max_embed_chars derives the right character limit."""

    def _make_processor(self):
        """Create an IndexProcessor without triggering DB or model loading."""
        with patch("pipeline.processors.indexing.indexer.get_db"), patch(
            "pipeline.processors.indexing.indexer.PostgresClient"
        ):
            return IndexProcessor()

    def test_uses_smallest_model_limit(self):
        """When multiple models have max_tokens, use the smallest."""
        proc = self._make_processor()
        fake_vectors = {
            "azure_small": {"max_tokens": 8192},
            "azure_large": {"max_tokens": 8192},
            "e5_large": {"max_tokens": 512},
        }
        with patch("pipeline.processors.indexing.indexer.DB_VECTORS", fake_vectors):
            result = proc._compute_max_embed_chars(
                ["azure_small", "azure_large", "e5_large"]
            )
        assert result == 512 * _CHARS_PER_TOKEN

    def test_single_model_with_max_tokens(self):
        """Single target model with max_tokens configured."""
        proc = self._make_processor()
        fake_vectors = {"azure_small": {"max_tokens": 8192}}
        with patch("pipeline.processors.indexing.indexer.DB_VECTORS", fake_vectors):
            result = proc._compute_max_embed_chars(["azure_small"])
        assert result == 8192 * _CHARS_PER_TOKEN

    def test_fallback_when_no_max_tokens(self):
        """Models without max_tokens fall back to _DEFAULT_MAX_EMBED_TOKENS."""
        proc = self._make_processor()
        fake_vectors = {"e5_large": {"size": 1024, "model_id": "e5"}}
        with patch("pipeline.processors.indexing.indexer.DB_VECTORS", fake_vectors):
            result = proc._compute_max_embed_chars(["e5_large"])
        assert result == _DEFAULT_MAX_EMBED_TOKENS * _CHARS_PER_TOKEN

    def test_empty_targets_uses_default(self):
        """No targets at all falls back to _DEFAULT_MAX_EMBED_TOKENS."""
        proc = self._make_processor()
        with patch("pipeline.processors.indexing.indexer.DB_VECTORS", {}):
            result = proc._compute_max_embed_chars([])
        assert result == _DEFAULT_MAX_EMBED_TOKENS * _CHARS_PER_TOKEN

    def test_mixed_models_only_considers_those_with_limit(self):
        """Models without max_tokens are ignored; limit comes from those that have it."""
        proc = self._make_processor()
        fake_vectors = {
            "azure_small": {"max_tokens": 8192},
            "e5_large": {"size": 1024},  # no max_tokens
        }
        with patch("pipeline.processors.indexing.indexer.DB_VECTORS", fake_vectors):
            result = proc._compute_max_embed_chars(["azure_small", "e5_large"])
        assert result == 8192 * _CHARS_PER_TOKEN

    def test_unknown_model_name_ignored(self):
        """A target not in DB_VECTORS is silently skipped."""
        proc = self._make_processor()
        fake_vectors = {"azure_small": {"max_tokens": 8192}}
        with patch("pipeline.processors.indexing.indexer.DB_VECTORS", fake_vectors):
            result = proc._compute_max_embed_chars(["azure_small", "nonexistent"])
        assert result == 8192 * _CHARS_PER_TOKEN


class TestFilterValidChunks:
    """Test _filter_valid_chunks removes empty chunks and truncates oversized ones."""

    def _make_processor(self, max_embed_chars=None):
        with patch("pipeline.processors.indexing.indexer.get_db"), patch(
            "pipeline.processors.indexing.indexer.PostgresClient"
        ):
            proc = IndexProcessor()
        if max_embed_chars is not None:
            proc._max_embed_chars = max_embed_chars
        return proc

    def test_filters_empty_chunks(self):
        """Chunks with empty or whitespace-only text are removed."""
        proc = self._make_processor(max_embed_chars=100000)
        chunks = [
            {"text": "valid text"},
            {"text": ""},
            {"text": "   "},
            {"text": "also valid"},
        ]
        result = proc._filter_valid_chunks(chunks)
        assert len(result) == 2
        assert result[0]["text"] == "valid text"
        assert result[1]["text"] == "also valid"

    def test_truncates_oversized_chunks(self):
        """Chunks exceeding max_embed_chars are truncated."""
        max_chars = 100
        proc = self._make_processor(max_embed_chars=max_chars)
        long_text = "x" * 500
        chunks = [{"text": long_text}]
        result = proc._filter_valid_chunks(chunks)
        assert len(result) == 1
        assert len(result[0]["text"]) == max_chars

    def test_does_not_truncate_short_chunks(self):
        """Chunks within the limit are left unchanged."""
        proc = self._make_processor(max_embed_chars=1000)
        text = "short chunk"
        chunks = [{"text": text}]
        result = proc._filter_valid_chunks(chunks)
        assert result[0]["text"] == text

    def test_truncation_at_exact_boundary(self):
        """A chunk exactly at the limit is not truncated."""
        max_chars = 50
        proc = self._make_processor(max_embed_chars=max_chars)
        text = "a" * max_chars
        chunks = [{"text": text}]
        result = proc._filter_valid_chunks(chunks)
        assert len(result[0]["text"]) == max_chars

    def test_mixed_chunks_only_oversized_truncated(self):
        """Only oversized chunks are truncated; short ones are untouched."""
        max_chars = 100
        proc = self._make_processor(max_embed_chars=max_chars)
        chunks = [
            {"text": "short"},
            {"text": "y" * 200},
            {"text": "normal length text here"},
            {"text": "z" * 300},
        ]
        result = proc._filter_valid_chunks(chunks)
        assert len(result) == 4
        assert result[0]["text"] == "short"
        assert len(result[1]["text"]) == max_chars
        assert result[2]["text"] == "normal length text here"
        assert len(result[3]["text"]) == max_chars

    def test_uses_default_when_no_max_embed_chars_attr(self):
        """Falls back to _DEFAULT_MAX_EMBED_TOKENS * _CHARS_PER_TOKEN."""
        proc = self._make_processor()
        # Don't set _max_embed_chars — should use default
        default_limit = _DEFAULT_MAX_EMBED_TOKENS * _CHARS_PER_TOKEN
        text = "a" * (default_limit + 100)
        chunks = [{"text": text}]
        result = proc._filter_valid_chunks(chunks)
        assert len(result[0]["text"]) == default_limit
