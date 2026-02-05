"""
test_stages.py - Tests for stage tracking functionality

Tests the new stage tracking system that records success/fail + timestamp
for each processing stage (download, parse, summarize, tag, index).
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from pipeline.db import make_stage, update_stages


class TestMakeStage:
    """Test make_stage helper function"""

    def test_success_stage(self):
        """Test creating a successful stage"""
        stage = make_stage(success=True)

        assert stage["success"] is True
        assert "at" in stage
        assert "error" not in stage

        # Verify timestamp is valid ISO format
        timestamp = stage["at"]
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert dt is not None

    def test_failed_stage_with_error(self):
        """Test creating a failed stage with error message"""
        stage = make_stage(success=False, error="Connection timeout")

        assert stage["success"] is False
        assert stage["error"] == "Connection timeout"
        assert "at" in stage

    def test_stage_with_metadata(self):
        """Test creating a stage with additional metadata"""
        stage = make_stage(
            success=True,
            page_count=45,
            word_count=12000,
            method="llm_summary",
        )

        assert stage["success"] is True
        assert stage["page_count"] == 45
        assert stage["word_count"] == 12000
        assert stage["method"] == "llm_summary"

    def test_stage_ignores_none_metadata(self):
        """Test that None metadata values are not included"""
        stage = make_stage(success=True, page_count=None, word_count=100)

        assert stage["success"] is True
        assert "page_count" not in stage
        assert stage["word_count"] == 100

    def test_stage_timestamp_is_utc(self):
        """Test that timestamp is in UTC"""
        stage = make_stage(success=True)

        timestamp = stage["at"]
        # Should contain timezone info (either +00:00 or Z)
        assert "+" in timestamp or "Z" in timestamp


class TestUpdateStages:
    """Test update_stages helper function"""

    def test_update_empty_stages(self):
        """Test adding a stage to empty/None stages"""
        stage_info = make_stage(success=True)
        stages = update_stages(None, "download", stage_info)

        assert "download" in stages
        assert stages["download"]["success"] is True

    def test_update_existing_stages(self):
        """Test adding a new stage to existing stages"""
        existing = {
            "download": {"success": True, "at": "2025-01-01T00:00:00+00:00"},
        }
        new_stage = make_stage(success=True, page_count=50)

        stages = update_stages(existing, "parse", new_stage)

        assert "download" in stages
        assert "parse" in stages
        assert stages["parse"]["page_count"] == 50
        # Original download stage should be preserved
        assert stages["download"]["at"] == "2025-01-01T00:00:00+00:00"

    def test_update_overwrites_same_stage(self):
        """Test that updating same stage overwrites it"""
        existing = {
            "parse": {
                "success": False,
                "at": "2025-01-01T00:00:00+00:00",
                "error": "Failed",
            },
        }
        new_stage = make_stage(success=True, page_count=50)

        stages = update_stages(existing, "parse", new_stage)

        assert stages["parse"]["success"] is True
        assert "error" not in stages["parse"]
        assert stages["parse"]["page_count"] == 50

    def test_update_preserves_other_stages(self):
        """Test that updating one stage preserves others"""
        existing = {
            "download": {"success": True, "at": "2025-01-01T00:00:00+00:00"},
            "parse": {"success": True, "at": "2025-01-01T00:01:00+00:00"},
        }
        new_stage = make_stage(success=True)

        stages = update_stages(existing, "summarize", new_stage)

        assert len(stages) == 3
        assert "download" in stages
        assert "parse" in stages
        assert "summarize" in stages


class TestBaseProcessorStageUpdates:
    """Test BaseProcessor.build_stage_updates method"""

    def test_build_stage_updates_success(self):
        """Test building stage updates for success"""
        # Import directly from base module to avoid triggering full package import
        from pipeline.processors.base import BaseProcessor

        # Create a concrete subclass for testing
        class TestProcessor(BaseProcessor):
            name = "TestProcessor"
            stage_name = "test"

            def process_document(self, doc):
                return {}

        processor = TestProcessor()
        doc = {"id": "123", "title": "Test Doc"}

        updates = processor.build_stage_updates(doc, success=True, chunks_count=50)

        assert "sys_stages" in updates
        assert "test" in updates["sys_stages"]
        assert updates["sys_stages"]["test"]["success"] is True
        assert updates["sys_stages"]["test"]["chunks_count"] == 50

    def test_build_stage_updates_failure(self):
        """Test building stage updates for failure"""
        from pipeline.processors.base import BaseProcessor

        class TestProcessor(BaseProcessor):
            name = "TestProcessor"
            stage_name = "test"

            def process_document(self, doc):
                return {}

        processor = TestProcessor()
        doc = {"id": "123"}

        updates = processor.build_stage_updates(
            doc, success=False, error="Something failed"
        )

        assert updates["sys_stages"]["test"]["success"] is False
        assert updates["sys_stages"]["test"]["error"] == "Something failed"

    def test_build_stage_updates_preserves_existing(self):
        """Test that existing stages are preserved"""
        from pipeline.processors.base import BaseProcessor

        class TestProcessor(BaseProcessor):
            name = "TestProcessor"
            stage_name = "summarize"

            def process_document(self, doc):
                return {}

        processor = TestProcessor()
        doc = {
            "id": "123",
            "sys_stages": {
                "download": {"success": True, "at": "2025-01-01T00:00:00+00:00"},
                "parse": {"success": True, "at": "2025-01-01T00:01:00+00:00"},
            },
        }

        updates = processor.build_stage_updates(doc, success=True, method="llm")

        # Should have all three stages
        assert "download" in updates["sys_stages"]
        assert "parse" in updates["sys_stages"]
        assert "summarize" in updates["sys_stages"]


class TestScanProcessorStages:
    """Test stage tracking in ScanProcessor"""

    def test_new_document_has_download_stage(self):
        """Test that new documents get a download stage"""
        from pipeline.processors.scanning.scanner import ScanProcessor

        mock_db = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create directory structure
            pdf_dir = Path(temp_dir) / "uneg" / "pdfs" / "UNDP" / "2023"
            pdf_dir.mkdir(parents=True)

            # Create test file
            pdf_path = pdf_dir / "Test_123.pdf"
            pdf_path.write_text("mock pdf")

            json_path = pdf_path.with_suffix(".json")
            json_path.write_text(
                json.dumps({"title": "Test", "node_id": 123, "pdf_url": "http://x.com"})
            )

            processor = ScanProcessor(base_dir=temp_dir, db=mock_db)
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
            existing_checksums = {}

            result = processor._process_metadata_file(
                json_path, stats, existing_checksums
            )

            assert result is not None
            _, metadata = result

            assert "sys_stages" in metadata
            assert "download" in metadata["sys_stages"]
            assert metadata["sys_stages"]["download"]["success"] is True
            assert "at" in metadata["sys_stages"]["download"]

    def test_error_document_has_failed_download_stage(self):
        """Test that error files get a failed download stage"""
        from pipeline.processors.scanning.scanner import ScanProcessor

        mock_db = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create directory structure
            pdf_dir = Path(temp_dir) / "uneg" / "pdfs" / "UNDP" / "2023"
            pdf_dir.mkdir(parents=True)

            # Create error file
            error_path = pdf_dir / "Failed_123.error"
            error_path.write_text("HTTP 404: Not Found")

            # Create matching JSON
            json_path = pdf_dir / "Failed_123.json"
            json_path.write_text(
                json.dumps({"title": "Failed", "pdf_url": "http://x.com/fail.pdf"})
            )

            processor = ScanProcessor(base_dir=temp_dir, db=mock_db)
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
            existing_checksums = {}

            result = processor._process_metadata_file(
                json_path, stats, existing_checksums
            )

            assert result is not None
            _, metadata = result

            assert "sys_stages" in metadata
            assert "download" in metadata["sys_stages"]
            assert metadata["sys_stages"]["download"]["success"] is False
            assert metadata["sys_stages"]["download"]["error"] == "HTTP 404: Not Found"


class TestProcessorStageNames:
    """Test that all processors have correct stage_name"""

    def test_scan_processor_stage_name(self):
        """Test ScanProcessor has correct stage_name"""
        from pipeline.processors.scanning.scanner import ScanProcessor

        assert ScanProcessor.stage_name == "download"

    def test_parse_processor_stage_name(self):
        """Test ParseProcessor has correct stage_name"""
        from pipeline.processors.parsing.parser import ParseProcessor

        assert ParseProcessor.stage_name == "parse"

    def test_summarize_processor_stage_name(self):
        """Test SummarizeProcessor has correct stage_name"""
        from pipeline.processors.summarization.summarizer import SummarizeProcessor

        assert SummarizeProcessor.stage_name == "summarize"

    def test_tagger_processor_stage_name(self):
        """Test TaggerProcessor has correct stage_name"""
        from pipeline.processors.tagging.tagger import TaggerProcessor

        assert TaggerProcessor.stage_name == "tag"

    def test_index_processor_stage_name(self):
        """Test IndexProcessor has correct stage_name"""
        from pipeline.processors.indexing.indexer import IndexProcessor

        assert IndexProcessor.stage_name == "index"


class TestStageIntegration:
    """Integration tests for stage tracking flow"""

    def test_full_stage_progression(self):
        """Test simulating full stage progression"""
        doc = {"id": "123", "title": "Test"}

        # Simulate download stage
        download_stage = make_stage(success=True)
        doc["stages"] = update_stages(None, "download", download_stage)

        assert doc["stages"]["download"]["success"] is True

        # Simulate parse stage
        parse_stage = make_stage(success=True, page_count=50, word_count=10000)
        doc["stages"] = update_stages(doc["stages"], "parse", parse_stage)

        assert len(doc["stages"]) == 2
        assert doc["stages"]["parse"]["page_count"] == 50

        # Simulate summarize stage
        summarize_stage = make_stage(success=True, method="llm_summary")
        doc["stages"] = update_stages(doc["stages"], "summarize", summarize_stage)

        assert len(doc["stages"]) == 3
        assert doc["stages"]["summarize"]["method"] == "llm_summary"

        # Simulate tag stage
        tag_stage = make_stage(success=True, sections_count=15)
        doc["stages"] = update_stages(doc["stages"], "tag", tag_stage)

        assert len(doc["stages"]) == 4

        # Simulate index stage
        index_stage = make_stage(success=True, chunks_count=87)
        doc["stages"] = update_stages(doc["stages"], "index", index_stage)

        # Final verification
        assert len(doc["stages"]) == 5
        assert all(
            doc["stages"][s]["success"]
            for s in ["download", "parse", "summarize", "tag", "index"]
        )

    def test_stage_failure_stops_progression(self):
        """Test that a failed stage is recorded correctly"""
        doc = {"id": "123", "title": "Test"}

        # Download succeeds
        download_stage = make_stage(success=True)
        doc["stages"] = update_stages(None, "download", download_stage)

        # Parse fails
        parse_stage = make_stage(success=False, error="Out of memory")
        doc["stages"] = update_stages(doc["stages"], "parse", parse_stage)

        assert doc["stages"]["download"]["success"] is True
        assert doc["stages"]["parse"]["success"] is False
        assert doc["stages"]["parse"]["error"] == "Out of memory"
        # No summarize stage yet
        assert "summarize" not in doc["stages"]
