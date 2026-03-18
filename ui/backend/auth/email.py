"""Email sending utilities for verification and password reset."""

import logging
import os
from email.message import EmailMessage

import aiosmtplib

logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@evidencelab.ai")
# Disable STARTTLS for local dev servers (e.g. Mailpit on port 1025)
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() != "false"

# Brand constants used in email templates
_BRAND_PRIMARY = "#5B8FA8"
_BRAND_PRIMARY_DARK = "#4A7490"
_BRAND_TEXT = "#2C3E50"
_BRAND_TEXT_SECONDARY = "#6B7876"
_BRAND_BORDER = "#D1D9D7"
_BRAND_BG = "#fafbfc"

# Fonts loaded from Google Fonts in the email <head>
_FONT_HEADING = "'Poppins', sans-serif"
_FONT_BODY = (
    "'Open Sans', -apple-system, BlinkMacSystemFont, " "'Segoe UI', Roboto, sans-serif"
)

# Shared inline styles (kept short for readability)
_STYLE_HEADING = (
    f"font-family:{_FONT_HEADING}; font-weight:600; " f"color:{_BRAND_PRIMARY_DARK}"
)
_STYLE_BTN = (
    f"display:inline-block; padding:12px 32px; "
    f"background-color:{_BRAND_PRIMARY}; color:#ffffff; "
    f"text-decoration:none; border-radius:6px; "
    f"font-weight:600; font-family:{_FONT_HEADING}; "
    f"font-size:14px"
)
_STYLE_LINK_HINT = f"font-size:13px; color:{_BRAND_TEXT_SECONDARY}"
_STYLE_FOOTER = f"font-size:12px; color:{_BRAND_TEXT_SECONDARY}"


def branded_html(body_inner: str) -> str:
    """Wrap email body content in a branded HTML template.

    Uses Evidence Lab brand colours, Poppins / Open Sans fonts, and
    the application logo.  The logo URL is built from ``APP_BASE_URL``
    so it works in both development and production.

    Args:
        body_inner: HTML fragment to place inside the card body.

    Returns:
        Complete HTML document string ready for ``send_email``.
    """
    base_url = os.environ.get("APP_BASE_URL", "http://localhost:3000")
    logo_url = f"{base_url}/logo.png"

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1.0">\n'
        "<title>Evidence Lab</title>\n"
        "<style>\n"
        "@import url("
        "'https://fonts.googleapis.com/css2"
        "?family=Poppins:wght@400;600;700"
        "&family=Open+Sans:wght@400;600&display=swap');\n"
        "</style>\n"
        "</head>\n"
        f'<body style="margin:0; padding:0; '
        f"background-color:{_BRAND_BG}; "
        f"font-family:{_FONT_BODY}; "
        f'color:{_BRAND_TEXT};">\n'
        '<table role="presentation" width="100%" '
        'cellpadding="0" cellspacing="0" '
        f'style="background-color:{_BRAND_BG};">\n'
        '<tr><td align="center" style="padding:40px 20px;">\n'
        "\n"
        "<!-- Card -->\n"
        '<table role="presentation" width="100%" '
        'cellpadding="0" cellspacing="0" '
        'style="max-width:520px; background-color:#ffffff; '
        f"border-radius:12px; border:1px solid {_BRAND_BORDER}; "
        'overflow:hidden;">\n'
        "\n"
        "<!-- Header -->\n"
        "<tr>\n"
        '<td align="center" style="padding:32px 40px 20px; '
        f'border-bottom:1px solid {_BRAND_BORDER};">\n'
        f'  <img src="{logo_url}" alt="Evidence Lab" '
        '  width="48" height="48" '
        '  style="display:block; margin-bottom:12px;">\n'
        f'  <span style="{_STYLE_HEADING}; '
        f'font-size:20px;">Evidence Lab</span>\n'
        "</td>\n"
        "</tr>\n"
        "\n"
        "<!-- Body -->\n"
        "<tr>\n"
        '<td style="padding:28px 40px 36px; font-size:15px; '
        f'line-height:1.6; color:{_BRAND_TEXT};">\n'
        f"{body_inner}\n"
        "</td>\n"
        "</tr>\n"
        "\n"
        "<!-- Footer -->\n"
        "<tr>\n"
        f'<td align="center" style="padding:16px 40px 24px; '
        f"border-top:1px solid {_BRAND_BORDER}; "
        f'{_STYLE_FOOTER};">\n'
        "  This is an automated message from Evidence Lab. "
        "Please do not reply.\n"
        "</td>\n"
        "</tr>\n"
        "\n"
        "</table>\n"
        "<!-- /Card -->\n"
        "\n"
        "</td></tr>\n"
        "</table>\n"
        "</body>\n"
        "</html>"
    )


def verification_email_html(verify_url: str) -> str:
    """Build the branded verification email body.

    Args:
        verify_url: Full URL the user clicks to verify their email.

    Returns:
        Complete HTML document string.
    """
    body = (
        f'<p style="margin:0 0 16px; {_STYLE_HEADING}; '
        f'font-size:17px;">\n'
        "  Verify your email address\n"
        "</p>\n"
        '<p style="margin:0 0 12px;">\n'
        "  Welcome to Evidence Lab! Please confirm your email\n"
        "  address to activate your account.\n"
        "</p>\n"
        '<p style="margin:0 0 24px; text-align:center;">\n'
        f'  <a href="{verify_url}" style="{_STYLE_BTN};">\n'
        "    Verify Email\n"
        "  </a>\n"
        "</p>\n"
        f'<p style="margin:0; {_STYLE_LINK_HINT};">\n'
        "  Or paste this link in your browser:<br>\n"
        f'  <a href="{verify_url}" '
        f'style="color:{_BRAND_PRIMARY}; '
        f'word-break:break-all;">'
        f"{verify_url}</a>\n"
        "</p>"
    )
    return branded_html(body)


def password_reset_email_html(reset_url: str) -> str:
    """Build the branded password-reset email body.

    Args:
        reset_url: Full URL the user clicks to reset their password.

    Returns:
        Complete HTML document string.
    """
    body = (
        f'<p style="margin:0 0 16px; {_STYLE_HEADING}; '
        f'font-size:17px;">\n'
        "  Reset your password\n"
        "</p>\n"
        '<p style="margin:0 0 12px;">\n'
        "  You requested a password reset for your Evidence Lab\n"
        "  account. Click the button below to choose a new\n"
        "  password.\n"
        "</p>\n"
        '<p style="margin:0 0 24px; text-align:center;">\n'
        f'  <a href="{reset_url}" style="{_STYLE_BTN};">\n'
        "    Reset Password\n"
        "  </a>\n"
        "</p>\n"
        f'<p style="margin:0 0 8px; {_STYLE_LINK_HINT};">\n'
        "  Or paste this link in your browser:<br>\n"
        f'  <a href="{reset_url}" '
        f'style="color:{_BRAND_PRIMARY}; '
        f'word-break:break-all;">'
        f"{reset_url}</a>\n"
        "</p>\n"
        f'<p style="margin:0; {_STYLE_LINK_HINT};">\n'
        "  If you didn't request this, you can safely ignore "
        "this email.\n"
        "</p>"
    )
    return branded_html(body)


async def send_email(to: str, subject: str, body_html: str) -> None:
    """Send an email via SMTP.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body_html: HTML body content.
    """
    if not SMTP_HOST:
        logger.warning("SMTP_HOST not configured — skipping email to %s", to)
        logger.info(
            "Email content for %s:\n  Subject: %s\n  Body: %s",
            to,
            subject,
            body_html,
        )
        return

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body_html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER or None,
            password=SMTP_PASSWORD or None,
            start_tls=SMTP_USE_TLS,
        )
        logger.info("Sent email to %s: %s", to, subject)
    except Exception:
        logger.exception("Failed to send email to %s", to)
        raise
