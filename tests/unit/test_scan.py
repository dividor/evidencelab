"""
test_scan.py - Tests for ScanProcessor

Tests the file scanning and Qdrant synchronization functionality.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.processors.scanning.scanner import (
    ScanProcessor,
    _make_relative_path,
    clean_title,
)


class TestMakeRelativePath:
    """Test _make_relative_path helper function"""

    def test_absolute_mount_path(self):
        """Test converting absolute mount path to relative"""
        path = "/mnt/files/evaluation-db/uneg/pdfs/UNDP/2023/Doc_123.pdf"
        result = _make_relative_path(path)
        assert result == "data/uneg/pdfs/UNDP/2023/Doc_123.pdf"

    def test_alternative_mount_path(self):
        """Test converting /mnt/data mount to relative"""
        path = "/mnt/data/uneg/pdfs/UNICEF/2024/Report_456.pdf"
        result = _make_relative_path(path)
        assert result == "data/uneg/pdfs/UNICEF/2024/Report_456.pdf"

    def test_cache_path(self):
        """Test cache paths are also converted"""
        path = "/mnt/files/evaluation-db/uneg/cache/parsed/doc_123.json"
        result = _make_relative_path(path)
        assert result == "data/uneg/cache/parsed/doc_123.json"

    def test_already_relative(self):
        """Test paths starting with data/ are unchanged"""
        path = "data/uneg/pdfs/UNDP/2023/Doc_123.pdf"
        result = _make_relative_path(path)
        assert result == path

    def test_dot_data_prefix(self):
        """Test ./data/ prefix is normalized"""
        path = "./data/uneg/pdfs/UNDP/2023/Doc_123.pdf"
        result = _make_relative_path(path)
        assert result == "data/uneg/pdfs/UNDP/2023/Doc_123.pdf"

    def test_windows_backslashes(self):
        """Test Windows-style paths are handled"""
        path = "C:\\data\\uneg\\pdfs\\UNDP\\2023\\Doc_123.pdf"
        result = _make_relative_path(path)
        # Should at least convert backslashes
        assert "\\" not in result


def test_clean_title_removes_url_suffix():
    title = "My Report - https://example.com/report"
    assert clean_title(title) == "My Report"

    no_suffix = "Simple Report"
    assert clean_title(no_suffix) == "Simple Report"


class TestScanProcessor:
    """Test ScanProcessor class functionality"""

    @pytest.fixture(autouse=True)
    def _mock_db(self):
        with patch("pipeline.processors.scanning.scanner.get_db") as mock_get_db:
            mock_get_db.return_value = MagicMock()
            yield

    def test_processor_initialization(self):
        """Test that processor initializes with correct settings"""
        processor = ScanProcessor(base_dir="./test/data")

        assert processor.name == "ScanProcessor"
        assert processor.base_dir == "./test/data"

    def test_scan_documents_finds_pdfs(self):
        """Test that scanner correctly discovers metadata files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test directory structure
            test_dir = Path(temp_dir) / "TestAgency" / "2023"
            test_dir.mkdir(parents=True)

            # Create test metadata files
            json_path = test_dir / "Test Document_12345.json"
            json_path.write_text(json.dumps({"title": "Test Document"}))
            json_path2 = test_dir / "Another_67890.json"
            json_path2.write_text(json.dumps({"title": "Another"}))

            # Scan directory
            processor = ScanProcessor(base_dir=temp_dir)
            processor.setup()
            documents = processor._scan_metadata_files()

            # Should find our test documents
            assert len(documents) == 2

    def test_scan_documents_finds_docx(self):
        """Test that scanner finds metadata files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "Agency"
            test_dir.mkdir()

            json_path = test_dir / "Document.json"
            json_path.write_text(json.dumps({"title": "Document"}))

            processor = ScanProcessor(base_dir=temp_dir)
            processor.setup()
            documents = processor._scan_metadata_files()

            assert len(documents) == 1
            assert documents[0].suffix == ".json"

    def test_scan_error_files(self):
        """Test that scanner processes .error files via metadata"""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "Agency"
            test_dir.mkdir()

            json_path = test_dir / "Failed_123.json"
            json_path.write_text(json.dumps({"title": "Failed"}))
            error_path = test_dir / "Failed_123.error"
            error_path.write_text("Download failed: 404")

            processor = ScanProcessor(base_dir=temp_dir)
            processor.setup()
            stats = {
                "new": 0,
                "file_changed": 0,
                "metadata_changed": 0,
                "both_changed": 0,
                "unchanged": 0,
                "no_metadata": 0,
                "errors": 0,
                "download_errors_new": 0,
                "download_errors_unchanged": 0,
                "duplicates": 0,
            }
            result = processor._process_metadata_file(
                json_path, stats, existing_checksums={}
            )

            assert result is not None
            _, metadata = result
            assert metadata["sys_status"] == "download_error"

    def test_compute_file_checksum(self):
        """Test file checksum computation"""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.txt"
            test_file.write_text("test content")

            processor = ScanProcessor(base_dir=temp_dir)
            checksum = processor._compute_file_checksum(str(test_file))

            # Should return a valid SHA-256 hex string
            assert len(checksum) == 64
            assert all(c in "0123456789abcdef" for c in checksum)

    def test_compute_json_checksum(self):
        """Test JSON checksum is consistent"""
        processor = ScanProcessor(base_dir="./test")

        metadata = {"title": "Test", "id": 123}
        checksum1 = processor._compute_json_checksum(metadata)
        checksum2 = processor._compute_json_checksum({"id": 123, "title": "Test"})

        # Order shouldn't matter (json is sorted)
        assert checksum1 == checksum2
        assert len(checksum1) == 64

    def test_load_metadata_cleans_title(self):
        """Test that metadata loading cleans URL suffixes from titles"""
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "test.json"
            json_path.write_text(
                json.dumps(
                    {"title": "Report Title - https://example.com/report.pdf", "id": 1}
                )
            )

            processor = ScanProcessor(base_dir=temp_dir)
            metadata = processor._load_metadata_from_json(str(json_path))

            assert metadata["title"] == "Report Title"
            assert "https://" not in metadata["title"]

    @patch("pipeline.processors.scanning.scanner.get_db")
    def test_process_document_file_stores_relative_path(self, mock_get_db):
        """Test that document processing stores relative filepath"""
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create structure mimicking the actual data layout
            pdf_dir = Path(temp_dir) / "uneg" / "pdfs" / "UNDP" / "2023"
            pdf_dir.mkdir(parents=True)

            pdf_path = pdf_dir / "Test_123.pdf"
            pdf_path.write_text("mock pdf")

            json_path = pdf_path.with_suffix(".json")
            json_path.write_text(
                json.dumps({"title": "Test", "node_id": 123, "pdf_url": "http://x.com"})
            )

            processor = ScanProcessor(base_dir=temp_dir, db=mock_db)
            processor.setup()

            stats = {"new": 0, "errors": 0}
            existing_checksums = {}

            result = processor._process_metadata_file(
                json_path, stats, existing_checksums
            )

            # Check that upsert was called with relative path
            assert result is not None
            _, metadata = result

            # Should have relative path
            assert metadata["sys_filepath"].startswith("data/")
            assert "/mnt/" not in metadata["sys_filepath"]
