"""Unit tests for the email sending utility."""

import pytest
from unittest.mock import AsyncMock, patch

from ui.backend.auth.email import send_email


class TestSendEmail:
    """Tests for the send_email utility function."""

    @pytest.mark.asyncio
    async def test_skips_when_smtp_host_not_configured(self):
        """When SMTP_HOST is empty, send_email should silently skip."""
        with patch("ui.backend.auth.email.SMTP_HOST", ""):
            # Should not raise
            await send_email("user@test.com", "Test", "<p>Hello</p>")

    @pytest.mark.asyncio
    async def test_sends_email_when_configured(self):
        """When SMTP is configured, send_email should call aiosmtplib.send."""
        with (
            patch("ui.backend.auth.email.SMTP_HOST", "smtp.example.com"),
            patch("ui.backend.auth.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send,
        ):
            await send_email("user@test.com", "Verify", "<p>Click here</p>")
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args
            assert call_kwargs.kwargs["hostname"] == "smtp.example.com"

    @pytest.mark.asyncio
    async def test_raises_on_smtp_failure(self):
        """When SMTP sending fails, the exception should propagate."""
        with (
            patch("ui.backend.auth.email.SMTP_HOST", "smtp.example.com"),
            patch(
                "ui.backend.auth.email.aiosmtplib.send",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Connection refused"),
            ),
        ):
            with pytest.raises(ConnectionError):
                await send_email("user@test.com", "Verify", "<p>Click here</p>")
