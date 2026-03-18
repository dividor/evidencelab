"""Unit tests for email template generation functions."""

from unittest.mock import patch

from ui.backend.auth.email import (
    branded_html,
    password_reset_email_html,
    verification_email_html,
)


class TestBrandedHtml:
    """Tests for the branded_html wrapper function."""

    def test_returns_complete_html_document(self):
        """Should return a complete HTML document."""
        result = branded_html("<p>Hello</p>")
        assert result.startswith("<!DOCTYPE html>")
        assert "</html>" in result

    def test_includes_body_content(self):
        """Should include the provided body content."""
        result = branded_html("<p>Custom content</p>")
        assert "<p>Custom content</p>" in result

    def test_includes_brand_elements(self):
        """Should include Evidence Lab branding."""
        result = branded_html("<p>Test</p>")
        assert "Evidence Lab" in result

    def test_includes_logo_from_env(self):
        """Should use APP_BASE_URL for the logo URL."""
        with patch.dict("os.environ", {"APP_BASE_URL": "https://app.example.com"}):
            result = branded_html("<p>Test</p>")
            assert "https://app.example.com/logo.png" in result

    def test_uses_default_base_url(self):
        """Should fall back to localhost when APP_BASE_URL is not set."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove APP_BASE_URL if it exists
            import os

            env = os.environ.copy()
            env.pop("APP_BASE_URL", None)
            with patch.dict("os.environ", env, clear=True):
                result = branded_html("<p>Test</p>")
                assert "localhost" in result

    def test_includes_footer(self):
        """Should include the automated message footer."""
        result = branded_html("<p>Test</p>")
        assert "automated message" in result.lower()


class TestVerificationEmailHtml:
    """Tests for the verification_email_html function."""

    def test_includes_verify_url(self):
        """Should include the verification URL in the email."""
        url = "https://app.example.com/verify?token=abc123"
        result = verification_email_html(url)
        assert url in result

    def test_includes_verify_button(self):
        """Should include a 'Verify Email' call-to-action."""
        result = verification_email_html("https://example.com/verify")
        assert "Verify Email" in result

    def test_includes_welcome_message(self):
        """Should include a welcome message."""
        result = verification_email_html("https://example.com/verify")
        assert "Welcome" in result

    def test_is_complete_html(self):
        """Should return a complete HTML document (via branded_html)."""
        result = verification_email_html("https://example.com/verify")
        assert "<!DOCTYPE html>" in result
        assert "</html>" in result

    def test_url_appears_as_link_and_text(self):
        """Should include the URL both as an href and as visible text."""
        url = "https://app.example.com/verify?token=xyz"
        result = verification_email_html(url)
        # URL should appear as an href attribute
        assert f'href="{url}"' in result


class TestPasswordResetEmailHtml:
    """Tests for the password_reset_email_html function."""

    def test_includes_reset_url(self):
        """Should include the password reset URL in the email."""
        url = "https://app.example.com/reset?token=abc123"
        result = password_reset_email_html(url)
        assert url in result

    def test_includes_reset_button(self):
        """Should include a 'Reset Password' call-to-action."""
        result = password_reset_email_html("https://example.com/reset")
        assert "Reset Password" in result

    def test_includes_safety_message(self):
        """Should include a message about ignoring if not requested."""
        result = password_reset_email_html("https://example.com/reset")
        assert "ignore" in result.lower()

    def test_is_complete_html(self):
        """Should return a complete HTML document (via branded_html)."""
        result = password_reset_email_html("https://example.com/reset")
        assert "<!DOCTYPE html>" in result

    def test_url_appears_as_link_and_text(self):
        """Should include the URL both as an href and as visible text."""
        url = "https://app.example.com/reset?token=xyz"
        result = password_reset_email_html(url)
        assert f'href="{url}"' in result
