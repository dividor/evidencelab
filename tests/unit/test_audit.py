"""Unit tests for the audit logging module."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from ui.backend.auth.audit import write_audit_event


class TestWriteAuditEvent:
    """Tests for the write_audit_event function."""

    @pytest.mark.asyncio
    async def test_writes_event_with_all_fields(self):
        """Audit event with all fields creates an AuditLog entry."""
        mock_session = AsyncMock()
        user_id = uuid.uuid4()

        async def mock_get_session():
            yield mock_session

        with patch(
            "ui.backend.auth.audit.get_async_session",
            return_value=mock_get_session(),
        ):
            await write_audit_event(
                "login_success",
                user_id=user_id,
                user_email="user@test.com",
                ip_address="192.168.1.1",
                details={"browser": "Chrome"},
            )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

        # Verify the AuditLog entry was created with correct fields
        entry = mock_session.add.call_args[0][0]
        assert entry.event_type == "login_success"
        assert entry.user_id == user_id
        assert entry.user_email == "user@test.com"
        assert entry.ip_address == "192.168.1.1"
        assert entry.details == {"browser": "Chrome"}

    @pytest.mark.asyncio
    async def test_writes_event_with_minimal_fields(self):
        """Audit event with only event_type should still succeed."""
        mock_session = AsyncMock()

        async def mock_get_session():
            yield mock_session

        with patch(
            "ui.backend.auth.audit.get_async_session",
            return_value=mock_get_session(),
        ):
            await write_audit_event("login_failure")

        mock_session.add.assert_called_once()
        entry = mock_session.add.call_args[0][0]
        assert entry.event_type == "login_failure"
        assert entry.user_id is None
        assert entry.user_email is None
        assert entry.ip_address is None
        assert entry.details is None

    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_error(self):
        """Audit logging must never break the request — degrade gracefully."""

        async def mock_get_session():
            raise ConnectionError("Database unavailable")
            yield  # pragma: no cover

        with patch(
            "ui.backend.auth.audit.get_async_session",
            return_value=mock_get_session(),
        ):
            # Should not raise
            await write_audit_event(
                "login_failure",
                user_email="user@test.com",
            )

    @pytest.mark.asyncio
    async def test_logs_exception_on_db_error(self):
        """Database errors should be logged, not swallowed silently."""

        async def mock_get_session():
            raise ConnectionError("Database unavailable")
            yield  # pragma: no cover

        with (
            patch(
                "ui.backend.auth.audit.get_async_session",
                return_value=mock_get_session(),
            ),
            patch("ui.backend.auth.audit.logger") as mock_logger,
        ):
            await write_audit_event("login_failure")
            mock_logger.exception.assert_called_once()
            assert "login_failure" in mock_logger.exception.call_args[0][1]

    @pytest.mark.asyncio
    async def test_commit_error_gracefully_handled(self):
        """If session.commit() fails, it should not propagate."""
        mock_session = AsyncMock()
        mock_session.commit.side_effect = RuntimeError("commit failed")

        async def mock_get_session():
            yield mock_session

        with patch(
            "ui.backend.auth.audit.get_async_session",
            return_value=mock_get_session(),
        ):
            # Should not raise
            await write_audit_event(
                "register",
                user_email="new@test.com",
            )
