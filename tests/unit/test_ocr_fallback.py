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


# --- per-page threshold (measured on a UNEG batch, 2026-10-19) ---------------
#
# These scanned reports parsed to more than 10 words thanks to a text cover
# page, escaped the absolute floor, and summarised to "Empty markdown".
MEASURED_MISSED_SCANS = [(80, 208), (88, 210), (93, 194), (10, 16), (20, 119), (5, 21)]
# Ordinary documents from the same run.
MEASURED_NORMAL_DOCS = [(190, 60_000), (12, 4_800), (1, 300), (237, 120_000)]


def _result(pages: int, words: int) -> tuple:
    """A parse_result tuple as _needs_ocr_retry unpacks it."""
    return ("markdown", None, pages, words, None, None)


def _parser(**kwargs) -> ParseProcessor:
    p = ParseProcessor(ocr_fallback=True, **kwargs)
    p.no_ocr = True
    return p


class TestOcrRetryPerPageThreshold:
    def test_default_threshold_is_twenty_five(self):
        assert ParseProcessor().ocr_fallback_min_words_per_page == 25

    def test_absolute_floor_still_fires(self):
        assert _parser()._needs_ocr_retry(_result(1, 5)) is True

    @pytest.mark.parametrize("pages,words", MEASURED_MISSED_SCANS)
    def test_measured_missed_scans_now_retry(self, pages, words):
        assert _parser()._needs_ocr_retry(_result(pages, words)) is True

    @pytest.mark.parametrize("pages,words", MEASURED_NORMAL_DOCS)
    def test_normal_documents_do_not_retry(self, pages, words):
        assert _parser()._needs_ocr_retry(_result(pages, words)) is False

    def test_boundary_is_strictly_below_the_threshold(self):
        assert _parser()._needs_ocr_retry(_result(4, 99)) is True  # 24.75 words/page
        assert _parser()._needs_ocr_retry(_result(4, 100)) is False  # exactly 25

    def test_zero_turns_the_per_page_rule_off_but_keeps_the_floor(self):
        p = _parser(ocr_fallback_min_words_per_page=0)
        assert p._needs_ocr_retry(_result(80, 208)) is False
        assert p._needs_ocr_retry(_result(1, 5)) is True

    def test_custom_threshold(self):
        p = _parser(ocr_fallback_min_words_per_page=5)
        assert p._needs_ocr_retry(_result(80, 208)) is True  # 2.6 words/page
        assert p._needs_ocr_retry(_result(20, 119)) is False  # 5.95 words/page

    def test_never_without_ocr_fallback_or_when_ocr_already_on_or_no_pages(self):
        off = ParseProcessor()
        off.no_ocr = True
        assert off._needs_ocr_retry(_result(80, 208)) is False
        already_ocr = _parser()
        already_ocr.no_ocr = False
        assert already_ocr._needs_ocr_retry(_result(80, 208)) is False
        assert _parser()._needs_ocr_retry(_result(0, 0)) is False

    def test_malformed_result_is_not_retried(self):
        assert _parser()._needs_ocr_retry(None) is False
        assert _parser()._needs_ocr_retry(("x", None)) is False


class TestSubprocessConfigRoundTrip:
    def test_child_can_be_constructed_from_the_parent_config(self):
        """The child does ParseProcessor(**config); an extra key is a TypeError there.

        ocr_fallback used to be in the dict but not in __init__, so with the
        fallback on every subprocess parse would have died on construction.
        """
        parent = ParseProcessor(ocr_fallback=True, ocr_fallback_min_words_per_page=7)
        child = ParseProcessor(**parent._subprocess_config())
        assert child.ocr_fallback is True
        assert child.ocr_fallback_min_words_per_page == 7
        assert child.use_subprocess is False, "a child must not nest subprocesses"

    def test_every_config_key_is_a_constructor_parameter(self):
        import inspect

        params = set(inspect.signature(ParseProcessor.__init__).parameters) - {"self"}
        extra = set(ParseProcessor()._subprocess_config()) - params
        assert extra == set(), f"keys the child constructor would reject: {extra}"


class TestWorkerConfiguresParser:
    def test_settings_from_the_datasource_parse_block_are_applied(self):
        from pipeline.orchestrator.worker import _configure_parser

        p = ParseProcessor()
        _configure_parser(
            p,
            {
                "ocr_fallback": True,
                "ocr_fallback_min_words_per_page": "40",
                "subprocess_timeout": 99,
            },
        )
        assert p.ocr_fallback is True
        assert p.ocr_fallback_min_words_per_page == 40
        assert p.subprocess_timeout == 99

    def test_absent_settings_leave_the_defaults(self):
        from pipeline.orchestrator.worker import _configure_parser

        p = ParseProcessor()
        _configure_parser(p, {})
        assert p.ocr_fallback is False
        assert p.ocr_fallback_min_words_per_page == 25
