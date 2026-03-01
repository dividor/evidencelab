"""
Unit tests for ParseProcessor glyph contamination detection and pypdf fallback.

Tests cover:
- _fix_glyph_contamination: glyph detection threshold and pypdf rebuild
- _fix_glyph_json: post-processing docling JSON to replace glyph text
"""

import json
from unittest.mock import MagicMock, patch

from pipeline.processors.parsing.parser import ParseProcessor
from pipeline.processors.parsing.parser_constants import PAGE_SEPARATOR


def _make_parser():
    """Create a ParseProcessor without initialising Docling converter."""
    with patch.object(ParseProcessor, "setup"):
        p = ParseProcessor.__new__(ParseProcessor)
        p.name = "ParseProcessor"
        return p


class TestGlyphDetection:
    """Test _fix_glyph_contamination detects and fixes glyph content."""

    def test_no_glyphs_unchanged(self, tmp_path):
        """Clean markdown should not be modified."""
        md = tmp_path / "doc.md"
        original = "This is a perfectly clean document with real text content."
        md.write_text(original)

        parser = _make_parser()
        result = parser._fix_glyph_contamination(md, str(tmp_path / "doc.pdf"))

        assert result is None
        assert md.read_text() == original

    def test_below_threshold_unchanged(self, tmp_path):
        """Markdown with glyphs below 30% threshold should not trigger fallback."""
        md = tmp_path / "doc.md"
        real_text = "A" * 800
        glyph_text = "/gid00028/gid01154" * 10  # 180 chars = ~18% of 980
        original = real_text + glyph_text
        md.write_text(original)

        parser = _make_parser()
        result = parser._fix_glyph_contamination(md, str(tmp_path / "doc.pdf"))

        assert result is None
        assert md.read_text() == original

    @patch("pipeline.processors.parsing.parser.PdfReader")
    def test_glyph_contamination_triggers_fallback(self, mock_reader_cls, tmp_path):
        """Markdown with >30% glyphs should be rebuilt from pypdf."""
        md = tmp_path / "doc.md"
        # 90% glyphs
        glyph_text = "/gid00028" * 100  # 900 chars
        real_text = "X" * 100
        md.write_text(glyph_text + real_text)

        # Mock pypdf
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page one content here."
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page two content here."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]
        mock_reader_cls.return_value = mock_reader

        pdf_path = str(tmp_path / "doc.pdf")
        parser = _make_parser()
        result = parser._fix_glyph_contamination(md, pdf_path)

        assert result is not None
        assert result == {1: "Page one content here.", 2: "Page two content here."}
        rebuilt = md.read_text()
        assert "Page one content here." in rebuilt
        assert "Page two content here." in rebuilt
        assert PAGE_SEPARATOR in rebuilt
        assert "/gid00028" not in rebuilt
        mock_reader_cls.assert_called_once_with(pdf_path)

    def test_non_pdf_not_called(self, tmp_path):
        """The method itself works on any file, but the caller gates on .pdf.

        Verify the method returns None for content without glyphs (simulating
        a non-PDF that would never have glyph contamination).
        """
        md = tmp_path / "doc.md"
        md.write_text("Normal DOCX content without any glyph patterns.")

        parser = _make_parser()
        result = parser._fix_glyph_contamination(md, str(tmp_path / "doc.docx"))

        assert result is None

    @patch("pipeline.processors.parsing.parser.PdfReader")
    def test_pypdf_empty_keeps_original(self, mock_reader_cls, tmp_path):
        """If pypdf extracts no text, keep the original markdown."""
        md = tmp_path / "doc.md"
        original = "/gid00028" * 200  # heavy glyphs
        md.write_text(original)

        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        parser = _make_parser()
        result = parser._fix_glyph_contamination(md, str(tmp_path / "doc.pdf"))

        assert result is None
        assert md.read_text() == original

    @patch("pipeline.processors.parsing.parser.PdfReader")
    def test_pypdf_exception_keeps_original(self, mock_reader_cls, tmp_path):
        """If pypdf raises, keep the original markdown."""
        md = tmp_path / "doc.md"
        original = "/gid00028" * 200
        md.write_text(original)

        mock_reader_cls.side_effect = Exception("corrupt pdf")

        parser = _make_parser()
        result = parser._fix_glyph_contamination(md, str(tmp_path / "doc.pdf"))

        assert result is None
        assert md.read_text() == original

    def test_short_content_skipped(self, tmp_path):
        """Very short markdown files should be skipped."""
        md = tmp_path / "doc.md"
        md.write_text("/gid00028" * 5)  # 45 chars, below 200 min

        parser = _make_parser()
        result = parser._fix_glyph_contamination(md, str(tmp_path / "doc.pdf"))

        assert result is None

    @patch("pipeline.processors.parsing.parser.PdfReader")
    def test_returns_page_number_mapping(self, mock_reader_cls, tmp_path):
        """Returned dict should use 1-based page numbers."""
        md = tmp_path / "doc.md"
        md.write_text("/gid00028" * 200)

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "First page."
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = ""  # empty page skipped
        mock_page3 = MagicMock()
        mock_page3.extract_text.return_value = "Third page."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2, mock_page3]
        mock_reader_cls.return_value = mock_reader

        parser = _make_parser()
        result = parser._fix_glyph_contamination(md, str(tmp_path / "doc.pdf"))

        assert result == {1: "First page.", 3: "Third page."}


class TestGlyphJson:
    """Test _fix_glyph_json replaces glyph text in docling JSON."""

    def _make_docling_json(self, texts_by_page):
        """Build a minimal docling JSON with text items grouped by page."""
        texts = []
        body_children = []
        for i, (page_no, text) in enumerate(texts_by_page):
            ref = f"#/texts/{i}"
            texts.append(
                {
                    "self_ref": ref,
                    "parent": {"$ref": "#/body"},
                    "children": [],
                    "content_layer": "body",
                    "label": "text",
                    "prov": [{"page_no": page_no, "bbox": {}}],
                    "text": text,
                }
            )
            body_children.append({"$ref": ref})
        return {
            "schema_name": "docling_core.types.doc.document.DoclingDocument",
            "version": "1.0.0",
            "name": "test",
            "origin": {},
            "furniture": {
                "self_ref": "#/furniture",
                "children": [],
                "content_layer": "furniture",
            },
            "body": {
                "self_ref": "#/body",
                "children": body_children,
                "content_layer": "body",
            },
            "groups": [],
            "texts": texts,
            "pictures": [],
            "tables": [],
            "key_value_items": [],
            "form_items": [],
            "pages": {},
        }

    def test_replaces_text_by_page(self, tmp_path):
        """Text items should be replaced with pypdf text by page number."""
        json_path = tmp_path / "doc.json"
        data = self._make_docling_json(
            [
                (1, "/gid00028/gid01154 garbage text"),
                (2, "/gid00028/gid00853 more garbage"),
            ]
        )
        json_path.write_text(json.dumps(data))

        pages_by_number = {1: "Real page one text.", 2: "Real page two text."}

        parser = _make_parser()
        parser._fix_glyph_json(json_path, pages_by_number)

        result = json.loads(json_path.read_text())
        assert result["texts"][0]["text"] == "Real page one text."
        assert result["texts"][1]["text"] == "Real page two text."

    def test_multiple_items_per_page(self, tmp_path):
        """First item on a page gets the text, subsequent items are cleared."""
        json_path = tmp_path / "doc.json"
        data = self._make_docling_json(
            [
                (1, "/gid00028 item A"),
                (1, "/gid01154 item B"),
                (1, "/gid00853 item C"),
                (2, "/gid00028 item D"),
            ]
        )
        json_path.write_text(json.dumps(data))

        pages_by_number = {1: "Full page one content.", 2: "Full page two content."}

        parser = _make_parser()
        parser._fix_glyph_json(json_path, pages_by_number)

        result = json.loads(json_path.read_text())
        assert result["texts"][0]["text"] == "Full page one content."
        assert result["texts"][1]["text"] == ""
        assert result["texts"][2]["text"] == ""
        assert result["texts"][3]["text"] == "Full page two content."

    def test_pages_not_in_json_skipped(self, tmp_path):
        """Pages from pypdf that have no JSON text items are silently skipped."""
        json_path = tmp_path / "doc.json"
        data = self._make_docling_json(
            [
                (1, "/gid00028 page one"),
            ]
        )
        json_path.write_text(json.dumps(data))

        # pypdf extracted pages 1, 2, 3 but JSON only has page 1
        pages_by_number = {1: "Page one.", 2: "Page two.", 3: "Page three."}

        parser = _make_parser()
        parser._fix_glyph_json(json_path, pages_by_number)

        result = json.loads(json_path.read_text())
        assert result["texts"][0]["text"] == "Page one."

    def test_empty_texts_array(self, tmp_path):
        """JSON with no text items should not fail."""
        json_path = tmp_path / "doc.json"
        data = self._make_docling_json([])
        json_path.write_text(json.dumps(data))

        parser = _make_parser()
        parser._fix_glyph_json(json_path, {1: "Some text."})

        result = json.loads(json_path.read_text())
        assert result["texts"] == []
