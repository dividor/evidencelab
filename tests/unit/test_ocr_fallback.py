"""Tests for OCR fallback feature in ParseProcessor."""

from unittest.mock import MagicMock, patch

import pytest

from pipeline.processors.parsing.parser import ParseProcessor


class TestOcrFallback:
    """Test OCR fallback behaviour."""

    def test_ocr_fallback_defaults_to_false(self):
        """Processor should have ocr_fallback disabled by default."""
        p = ParseProcessor()
        assert p.ocr_fallback is False

    def test_ocr_fallback_can_be_enabled(self):
        """ocr_fallback attribute can be set after init."""
        p = ParseProcessor()
        p.ocr_fallback = True
        assert p.ocr_fallback is True

    def test_ocr_fallback_included_in_subprocess_config(self):
        """Subprocess config dict should include ocr_fallback."""
        p = ParseProcessor()
        p.ocr_fallback = True
        p._is_setup = True

        # Access the subprocess config building
        config = {
            "output_dir": p.output_dir,
            "table_mode": p.table_mode,
            "no_ocr": p.no_ocr,
            "images_scale": p.images_scale,
            "enable_chunking": p.enable_chunking,
            "chunk_size": p.chunk_size,
            "chunk_threshold": p.chunk_threshold,
            "chunk_timeout": p.chunk_timeout,
            "use_subprocess": False,
            "enable_superscripts": p.enable_superscripts,
            "superscript_mode": p.superscript_mode,
            "ocr_fallback": p.ocr_fallback,
        }
        assert config["ocr_fallback"] is True

    def test_retry_with_ocr_returns_result_on_success(self):
        """_retry_with_ocr should return parse result when OCR succeeds."""
        p = ParseProcessor()
        p.ocr_fallback = True
        p.no_ocr = True
        p._is_setup = True
        p._converter = MagicMock()

        mock_result = ("/tmp/out.md", "# TOC", 2, 500, "en", "pdf")

        with (
            patch.object(p, "_init_converter"),
            patch.object(p, "_parse_document_internal", return_value=mock_result),
        ):
            result = p._retry_with_ocr("/tmp/test.pdf", "/tmp/out", None)

        assert result is not None
        assert result[3] == 500  # word_count
        # no_ocr should be restored
        assert p.no_ocr is True

    def test_retry_with_ocr_returns_none_on_failure(self):
        """_retry_with_ocr should return None when OCR parse also fails."""
        p = ParseProcessor()
        p.ocr_fallback = True
        p.no_ocr = True
        p._is_setup = True
        p._converter = MagicMock()

        mock_result = (None, None, None, None, None, None)

        with (
            patch.object(p, "_init_converter"),
            patch.object(p, "_parse_document_internal", return_value=mock_result),
        ):
            result = p._retry_with_ocr("/tmp/test.pdf", "/tmp/out", None)

        assert result is None
        assert p.no_ocr is True

    def test_retry_with_ocr_restores_state_on_exception(self):
        """_retry_with_ocr should restore no_ocr even if parsing throws."""
        p = ParseProcessor()
        p.ocr_fallback = True
        p.no_ocr = True
        p._is_setup = True
        p._converter = MagicMock()

        with (
            patch.object(p, "_init_converter"),
            patch.object(
                p,
                "_parse_document_internal",
                side_effect=RuntimeError("boom"),
            ),
        ):
            with pytest.raises(RuntimeError):
                p._retry_with_ocr("/tmp/test.pdf", "/tmp/out", None)

        assert p.no_ocr is True

    def test_parse_direct_triggers_ocr_fallback(self):
        """_parse_direct should invoke OCR fallback when words < threshold."""
        p = ParseProcessor()
        p.ocr_fallback = True
        p.no_ocr = True
        p._is_setup = True
        p._converter = MagicMock()

        # First parse: 0 words (image PDF)
        initial_result = ("/tmp/out.md", "# TOC", 2, 0, "en", "pdf")
        # OCR retry: 500 words
        ocr_result = ("/tmp/out.md", "# TOC", 2, 500, "en", "pdf")

        with (
            patch.object(
                p,
                "_parse_document_internal",
                return_value=initial_result,
            ),
            patch.object(
                p,
                "_retry_with_ocr",
                return_value=ocr_result,
            ) as mock_retry,
            patch.object(p, "_make_relative_path", return_value="/tmp/out"),
        ):
            result = p._parse_direct("/tmp/test.pdf", "/tmp/out", "Test", 1.0)

        mock_retry.assert_called_once()
        assert result["success"] is True
        assert result["updates"]["sys_ocr_applied"] is True
        assert result["updates"]["sys_word_count"] == 500

    def test_parse_direct_skips_ocr_when_words_sufficient(self):
        """_parse_direct should NOT invoke OCR when word count is ok."""
        p = ParseProcessor()
        p.ocr_fallback = True
        p.no_ocr = True
        p._is_setup = True
        p._converter = MagicMock()

        initial_result = ("/tmp/out.md", "# TOC", 5, 200, "en", "pdf")

        with (
            patch.object(
                p,
                "_parse_document_internal",
                return_value=initial_result,
            ),
            patch.object(
                p,
                "_retry_with_ocr",
            ) as mock_retry,
            patch.object(p, "_make_relative_path", return_value="/tmp/out"),
        ):
            result = p._parse_direct("/tmp/test.pdf", "/tmp/out", "Test", 1.0)

        mock_retry.assert_not_called()
        assert result["success"] is True
        assert result["updates"]["sys_ocr_applied"] is False

    def test_parse_direct_skips_ocr_when_disabled(self):
        """_parse_direct should NOT invoke OCR when ocr_fallback is False."""
        p = ParseProcessor()
        p.ocr_fallback = False
        p.no_ocr = True
        p._is_setup = True
        p._converter = MagicMock()

        initial_result = ("/tmp/out.md", "# TOC", 2, 0, "en", "pdf")

        with (
            patch.object(
                p,
                "_parse_document_internal",
                return_value=initial_result,
            ),
            patch.object(
                p,
                "_retry_with_ocr",
            ) as mock_retry,
            patch.object(p, "_make_relative_path", return_value="/tmp/out"),
        ):
            result = p._parse_direct("/tmp/test.pdf", "/tmp/out", "Test", 1.0)

        mock_retry.assert_not_called()
        assert result["updates"]["sys_ocr_applied"] is False
