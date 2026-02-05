"""
test_parse.py - Tests for ParseProcessor

Tests the document parsing functionality.
"""

import tempfile
from pathlib import Path

import pytest

from pipeline.processors.parsing.parser import ParseProcessor


class TestParseProcessor:
    """Test ParseProcessor class functionality"""

    def test_processor_initialization(self):
        """Test that processor initializes with correct default settings"""
        processor = ParseProcessor()

        assert processor.output_dir == "./data/parsed"
        assert processor.table_mode == "fast"
        assert processor.no_ocr is True
        assert processor.enable_chunking is False  # Disabled: produces different output
        assert processor.chunk_size == 50
        assert processor.chunk_threshold == 200
        assert processor.chunk_timeout == 300
        assert processor.name == "ParseProcessor"

    def test_processor_custom_initialization(self):
        """Test processor with custom parameters"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(
                output_dir=tmpdir,
                chunk_size=100,
                chunk_threshold=500,
                no_ocr=False,
            )

            assert processor.output_dir == tmpdir
            assert processor.chunk_size == 100
            assert processor.chunk_threshold == 500
            assert processor.no_ocr is False

    def test_create_output_folder(self):
        """Test output folder creation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True  # Skip setup for this test

            # Create a test filepath mimicking actual structure
            test_filepath = f"{tmpdir}/pdfs/TestAgency/2024/test_doc.pdf"
            Path(test_filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(test_filepath).write_text("test")

            output_folder = processor._create_output_folder(test_filepath)

            assert Path(output_folder).exists()

    def test_process_document_missing_filepath(self):
        """Test processing document with missing filepath"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._initialized = True

            result = processor.process_document({"id": "test", "title": "Test"})

            assert result["success"] is False
            assert "No filepath" in result["error"]

    def test_process_document_file_not_found(self):
        """Test processing document when file doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._initialized = True

            result = processor.process_document(
                {
                    "id": "test",
                    "map_title": "Test",
                    "sys_filepath": "/nonexistent/file.pdf",
                }
            )

            assert result["success"] is False
            assert "not found" in result["error"].lower()


class TestChunkingLogic:
    """Test PDF chunking functionality"""

    def test_chunking_parameters(self):
        """Test that chunking parameters are set correctly"""
        processor = ParseProcessor(chunk_size=25, chunk_threshold=50)

        assert processor.chunk_size == 25
        assert processor.chunk_threshold == 50

    def test_chunk_timeout_setting(self):
        """Test chunk timeout configuration"""
        processor = ParseProcessor(chunk_timeout=600)

        assert processor.chunk_timeout == 600

    def test_chunking_disabled(self):
        """Test that chunking can be disabled"""
        processor = ParseProcessor(enable_chunking=False)

        assert processor.enable_chunking is False


class TestLanguageDetection:
    """Test language detection functionality"""

    def test_detect_language_method_exists(self):
        """Test that language detection method exists"""
        processor = ParseProcessor()

        assert hasattr(processor, "_detect_language")
        assert callable(processor._detect_language)


def test_page_separator_constant():
    """Test that PAGE_SEPARATOR constant is defined"""
    from pipeline.processors.parsing.parser import PAGE_SEPARATOR

    assert PAGE_SEPARATOR is not None
    assert isinstance(PAGE_SEPARATOR, str)
    assert "Page Break" in PAGE_SEPARATOR


class TestFallbackTOCGeneration:
    """Test fallback TOC generation when Docling detects no section headers"""

    def test_numbered_sections_detected(self):
        """Test that numbered sections like '1. Introduction' are detected"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            # Create markdown with numbered sections
            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

Some intro text here.

1. Introduction

This is the introduction content.

------- Page 5 -------

2. Methodology

This describes the methodology.

2.1 Data Collection

Details about data collection.

------- Page 10 -------

3. Results

The results section.
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            assert len(toc_lines) >= 4
            # Check for main sections
            assert any("1. Introduction" in line for line in toc_lines)
            assert any("2. Methodology" in line for line in toc_lines)
            assert any("2.1" in line for line in toc_lines)
            assert any("3. Results" in line for line in toc_lines)

    def test_heading_levels_inferred_from_numbering(self):
        """Test that heading levels are correctly inferred from section numbering"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

1. Main Section

1.1 Subsection

1.1.1 Sub-subsection
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            # Find each heading
            main_section = next(
                (entry for entry in toc_lines if "1. Main Section" in entry), None
            )
            subsection = next((entry for entry in toc_lines if "1.1" in entry), None)
            subsubsection = next(
                (entry for entry in toc_lines if "1.1.1" in entry), None
            )

            assert main_section is not None
            assert "[H2]" in main_section  # Top level = H2
            assert subsection is not None
            assert "[H3]" in subsection  # One dot = H3
            assert subsubsection is not None
            assert "[H4]" in subsubsection  # Two dots = H4

    def test_page_numbers_tracked(self):
        """Test that page numbers are correctly tracked from page markers"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 3 -------

1. Introduction

------- Page 15 -------

2. Conclusion
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            intro = next(
                (entry for entry in toc_lines if "Introduction" in entry), None
            )
            conclusion = next(
                (entry for entry in toc_lines if "Conclusion" in entry), None
            )

            assert intro is not None
            assert "page 3" in intro
            assert conclusion is not None
            assert "page 15" in conclusion

    def test_french_keywords_detected(self):
        """Test that French section keywords are detected"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

Résumé

Le résumé du document.

------- Page 5 -------

Introduction

L'introduction.

------- Page 20 -------

Recommandations

Les recommandations.

------- Page 30 -------

Bibliographie

Les références.
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            assert len(toc_lines) >= 4
            assert any("Résumé" in line for line in toc_lines)
            assert any("Introduction" in line for line in toc_lines)
            assert any("Recommandations" in line for line in toc_lines)
            assert any("Bibliographie" in line for line in toc_lines)

    def test_spanish_keywords_detected(self):
        """Test that Spanish section keywords are detected"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

Resumen

El resumen del documento.

------- Page 10 -------

Introducción

La introducción.

------- Page 25 -------

Conclusión

La conclusión.
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            assert len(toc_lines) >= 3
            assert any("Resumen" in line for line in toc_lines)
            assert any("Introducción" in line for line in toc_lines)
            assert any("Conclusión" in line for line in toc_lines)

    def test_english_keywords_detected(self):
        """Test that English section keywords are detected"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

Abstract

The abstract.

------- Page 5 -------

Introduction

The introduction.

------- Page 30 -------

Conclusion

The conclusion.

------- Page 35 -------

References

The references.
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            assert len(toc_lines) >= 4
            assert any("Abstract" in line for line in toc_lines)
            assert any("Introduction" in line for line in toc_lines)
            assert any("Conclusion" in line for line in toc_lines)
            assert any("References" in line for line in toc_lines)

    def test_duplicates_avoided(self):
        """Test that duplicate headings are not included"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

1. Introduction

Some text.

------- Page 5 -------

1. Introduction

Repeated heading (shouldn't be included twice).
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            intro_count = sum(1 for entry in toc_lines if "1. Introduction" in entry)
            assert intro_count == 1

    def test_table_rows_skipped(self):
        """Test that table rows are not mistakenly detected as headings"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

| Column 1 | Column 2 |
|----------|----------|
| Introduction | Data |

1. Real Introduction

Actual content.
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            # Table row "Introduction" should not be detected
            # Only "1. Real Introduction" should be found
            assert len(toc_lines) == 1
            assert "1. Real Introduction" in toc_lines[0]

    def test_short_lines_skipped(self):
        """Test that very short lines are not detected as headings"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

1. A

Too short to be a heading.

1. Introduction Section Title

This is a valid heading.
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            # "1. A" is too short (title part < 4 chars) - pattern requires 3+ chars
            # "1. Introduction Section Title" should be detected
            assert len(toc_lines) == 1
            assert "Introduction Section Title" in toc_lines[0]

    def test_empty_file_returns_empty_list(self):
        """Test that empty file returns empty TOC list"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text("")

            toc_lines = processor._generate_fallback_toc(md_path)

            assert toc_lines == []

    def test_nonexistent_file_returns_empty_list(self):
        """Test that nonexistent file returns empty TOC list (graceful failure)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "nonexistent.md"

            toc_lines = processor._generate_fallback_toc(md_path)

            assert toc_lines == []

    def test_mixed_numbered_and_keyword_sections(self):
        """Test document with both numbered sections and keyword sections"""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = ParseProcessor(output_dir=tmpdir)
            processor._is_setup = True

            md_path = Path(tmpdir) / "test.md"
            md_path.write_text(
                """
------- Page 1 -------

Abstract

The abstract.

------- Page 3 -------

1. Introduction

The introduction.

------- Page 10 -------

2. Methodology

The methods.

------- Page 25 -------

Conclusion

The conclusion.

------- Page 30 -------

Bibliography

References.
"""
            )

            toc_lines = processor._generate_fallback_toc(md_path)

            # Should detect both numbered and keyword sections
            assert len(toc_lines) >= 5
            assert any("Abstract" in line for line in toc_lines)
            assert any("1. Introduction" in line for line in toc_lines)
            assert any("2. Methodology" in line for line in toc_lines)
            assert any("Conclusion" in line for line in toc_lines)
            assert any("Bibliography" in line for line in toc_lines)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
