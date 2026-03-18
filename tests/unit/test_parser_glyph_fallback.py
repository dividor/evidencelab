"""
Unit tests for ParseProcessor glyph contamination detection.

Tests cover:
- _check_glyph_contamination: glyph detection threshold and error raising
- Detection of /gidXXXXX glyph IDs
- Detection of GLYPH<c=N,font=...> markers from Docling
"""

from unittest.mock import patch

import pytest

from pipeline.processors.parsing.parser import ParseProcessor


def _make_parser():
    """Create a ParseProcessor without initialising Docling converter."""
    with patch.object(ParseProcessor, "setup"):
        p = ParseProcessor.__new__(ParseProcessor)
        p.name = "ParseProcessor"
        return p


class TestGlyphDetection:
    """Test _check_glyph_contamination detects glyph content and raises."""

    def test_no_glyphs_passes(self, tmp_path):
        """Clean markdown should not raise."""
        md = tmp_path / "doc.md"
        md.write_text(
            "This is a perfectly clean document with real text content. " * 10
        )

        parser = _make_parser()
        parser._check_glyph_contamination(md)  # should not raise

    def test_below_threshold_passes(self, tmp_path):
        """Markdown with glyphs below 10% threshold should not raise."""
        md = tmp_path / "doc.md"
        real_text = "A" * 900
        glyph_text = "/gid00028" * 5  # 45 chars = ~5% of 945
        md.write_text(real_text + glyph_text)

        parser = _make_parser()
        parser._check_glyph_contamination(md)  # should not raise

    def test_glyph_id_contamination_raises(self, tmp_path):
        """Markdown with >10% /gidXXXXX glyphs should raise ValueError."""
        md = tmp_path / "doc.md"
        glyph_text = "/gid00028" * 100  # 900 chars
        real_text = "X" * 100
        md.write_text(glyph_text + real_text)

        parser = _make_parser()
        with pytest.raises(ValueError, match="Glyph contamination detected"):
            parser._check_glyph_contamination(md)

    def test_glyph_marker_contamination_raises(self, tmp_path):
        """Markdown with GLYPH<c=N,font=...> markers should raise."""
        md = tmp_path / "doc.md"
        marker = "GLYPH<c=3,font=/PNLMND+Calibri-Light>"
        glyph_text = (marker + " ") * 50
        real_text = "X" * 100
        md.write_text(glyph_text + real_text)

        parser = _make_parser()
        with pytest.raises(ValueError, match="Glyph contamination detected"):
            parser._check_glyph_contamination(md)

    def test_glyph_marker_below_threshold_passes(self, tmp_path):
        """Few GLYPH markers in mostly clean text should not raise."""
        md = tmp_path / "doc.md"
        marker = "GLYPH<c=3,font=/PNLMND+Calibri>"
        real_text = "Normal document text. " * 100  # ~2200 chars
        glyph_text = (marker + " ") * 3  # ~120 chars = ~5%
        md.write_text(real_text + glyph_text)

        parser = _make_parser()
        parser._check_glyph_contamination(md)  # should not raise

    def test_mixed_glyph_types_raises(self, tmp_path):
        """Both /gid and GLYPH<> types combined should raise."""
        md = tmp_path / "doc.md"
        gid_text = "/gid00028" * 20  # 180 chars
        marker = "GLYPH<c=3,font=/KOTEBS+Arial>"
        marker_text = (marker + " ") * 20  # ~620 chars
        real_text = "X" * 200
        md.write_text(gid_text + marker_text + real_text)

        parser = _make_parser()
        with pytest.raises(ValueError, match="Glyph contamination detected"):
            parser._check_glyph_contamination(md)

    def test_error_message_includes_percentage(self, tmp_path):
        """Error message should include the glyph percentage."""
        md = tmp_path / "doc.md"
        md.write_text("/gid00028" * 200)

        parser = _make_parser()
        with pytest.raises(ValueError, match=r"\d+% of parsed text"):
            parser._check_glyph_contamination(md)

    def test_error_message_includes_docling_bug_url(self, tmp_path):
        """Error message should reference the docling issue."""
        md = tmp_path / "doc.md"
        md.write_text("/gid00028" * 200)

        parser = _make_parser()
        with pytest.raises(ValueError, match="docling-project/docling/issues/2334"):
            parser._check_glyph_contamination(md)

    def test_error_details_gid(self, tmp_path):
        """Error for /gid contamination should mention /gidXXXXX IDs."""
        md = tmp_path / "doc.md"
        md.write_text("/gid00028" * 200)

        parser = _make_parser()
        with pytest.raises(ValueError, match="gidXXXXX IDs"):
            parser._check_glyph_contamination(md)

    def test_error_details_marker(self, tmp_path):
        """Error for GLYPH<> contamination should mention markers."""
        md = tmp_path / "doc.md"
        marker = "GLYPH<c=3,font=/PNLMND+Calibri-Light>"
        md.write_text((marker + " ") * 100)

        parser = _make_parser()
        with pytest.raises(ValueError, match=r"GLYPH<> markers"):
            parser._check_glyph_contamination(md)

    def test_short_content_skipped(self, tmp_path):
        """Very short markdown files should be skipped."""
        md = tmp_path / "doc.md"
        md.write_text("/gid00028" * 5)  # 45 chars, below 200 min

        parser = _make_parser()
        parser._check_glyph_contamination(md)  # should not raise

    def test_missing_file_skipped(self, tmp_path):
        """Missing file should not raise."""
        md = tmp_path / "nonexistent.md"

        parser = _make_parser()
        parser._check_glyph_contamination(md)  # should not raise
