"""Unit tests for structured JSON logging (ASVS V7.1.3)."""

import json
import logging
from datetime import datetime
from unittest.mock import patch

from ui.backend.utils.app_state import JSONLogFormatter, setup_logging


class TestJSONLogFormatter:
    """Verify JSON log output structure."""

    def _make_record(self, msg="test message", level=logging.INFO, **kwargs):
        """Create a LogRecord for testing."""
        record = logging.LogRecord(
            name="test.logger",
            level=level,
            pathname="test_logging.py",
            lineno=42,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for key, val in kwargs.items():
            setattr(record, key, val)
        return record

    def test_output_is_valid_json(self):
        """Formatted output must be parseable JSON."""
        formatter = JSONLogFormatter()
        record = self._make_record()
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_includes_required_fields(self):
        """Output must contain all required structured fields."""
        formatter = JSONLogFormatter()
        record = self._make_record()
        parsed = json.loads(formatter.format(record))
        for field in (
            "timestamp",
            "level",
            "logger",
            "message",
            "module",
            "function",
            "line",
        ):
            assert field in parsed, f"Missing required field: {field}"

    def test_message_content(self):
        """Message field should contain the log message text."""
        formatter = JSONLogFormatter()
        record = self._make_record("hello world")
        parsed = json.loads(formatter.format(record))
        assert parsed["message"] == "hello world"

    def test_level_name(self):
        """Level field should contain the level name string."""
        formatter = JSONLogFormatter()
        record = self._make_record(level=logging.WARNING)
        parsed = json.loads(formatter.format(record))
        assert parsed["level"] == "WARNING"

    def test_includes_exception(self):
        """Exception info should appear in the 'exception' field."""
        formatter = JSONLogFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = self._make_record()
            record.exc_info = sys.exc_info()
        parsed = json.loads(formatter.format(record))
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "boom" in parsed["exception"]

    def test_includes_extra_fields(self):
        """Extra security-relevant fields should be included when present."""
        formatter = JSONLogFormatter()
        record = self._make_record(user_id="abc-123", ip_address="10.0.0.1")
        parsed = json.loads(formatter.format(record))
        assert parsed["user_id"] == "abc-123"
        assert parsed["ip_address"] == "10.0.0.1"

    def test_extra_fields_absent_when_not_set(self):
        """Extra fields should not appear when not set on the record."""
        formatter = JSONLogFormatter()
        record = self._make_record()
        parsed = json.loads(formatter.format(record))
        assert "user_id" not in parsed
        assert "ip_address" not in parsed

    def test_timestamp_is_utc_iso(self):
        """Timestamp should be a parseable UTC ISO 8601 string."""
        formatter = JSONLogFormatter()
        record = self._make_record()
        parsed = json.loads(formatter.format(record))
        ts = parsed["timestamp"]
        # Should be parseable and contain timezone info
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None


class TestSetupLogging:
    """Verify setup_logging respects LOG_FORMAT env var."""

    def test_text_format_is_default(self):
        """Without LOG_FORMAT, handlers should use standard text formatter."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove LOG_FORMAT if present
            import os

            os.environ.pop("LOG_FORMAT", None)
            logger = setup_logging()
            handler = (
                logger.handlers[0]
                if logger.handlers
                else logging.getLogger().handlers[0]
            )
            assert not isinstance(handler.formatter, JSONLogFormatter)

    def test_json_format_when_configured(self):
        """With LOG_FORMAT=json, handlers should use JSONLogFormatter."""
        with patch.dict("os.environ", {"LOG_FORMAT": "json"}, clear=False):
            setup_logging()
            root_handlers = logging.getLogger().handlers
            # At least one handler should have JSONLogFormatter
            json_handlers = [
                h for h in root_handlers if isinstance(h.formatter, JSONLogFormatter)
            ]
            assert len(json_handlers) > 0
