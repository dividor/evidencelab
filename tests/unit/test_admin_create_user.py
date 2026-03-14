"""Tests for admin user creation schema and endpoint logic."""

import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import AdminUserCreate

# ---------------------------------------------------------------------------
# AdminUserCreate schema validation
# ---------------------------------------------------------------------------


class TestAdminUserCreateSchema:
    """Tests for the AdminUserCreate Pydantic schema."""

    def test_valid_payload(self):
        """Minimal valid payload is accepted."""
        test_pw = "Secret123"  # pragma: allowlist secret  # noqa: S105
        data = AdminUserCreate(email="new@example.com", password=test_pw)
        assert data.email == "new@example.com"
        assert data.password == test_pw  # pragma: allowlist secret
        assert data.first_name is None
        assert data.last_name is None

    def test_with_name(self):
        """Optional first_name/last_name are accepted and preserved."""
        data = AdminUserCreate(
            email="user@test.org",
            password="Passw0rd!",  # pragma: allowlist secret
            first_name="Jane",
            last_name="Doe",
        )
        assert data.first_name == "Jane"
        assert data.last_name == "Doe"

    def test_first_name_stripped(self):
        """Leading/trailing whitespace is stripped from first_name."""
        data = AdminUserCreate(
            email="a@b.com",
            password="Test1234",  # pragma: allowlist secret
            first_name="  Alice  ",
        )
        assert data.first_name == "Alice"

    def test_blank_first_name_becomes_none(self):
        """A blank first_name is normalised to None."""
        data = AdminUserCreate(
            email="a@b.com",
            password="Test1234",  # pragma: allowlist secret
            first_name="   ",
        )
        assert data.first_name is None

    def test_email_required(self):
        """Email is required."""
        with pytest.raises(ValidationError):
            AdminUserCreate(password="Secret123")  # pragma: allowlist secret

    def test_password_required(self):
        """Password is required."""
        with pytest.raises(ValidationError):
            AdminUserCreate(email="a@b.com")

    def test_email_max_length(self):
        """Email exceeding 320 chars is rejected."""
        long_email = "a" * 310 + "@example.com"  # 322 chars
        with pytest.raises(ValidationError, match="320"):
            AdminUserCreate(
                email=long_email,
                password="Secret123",  # pragma: allowlist secret  # noqa: S105
            )

    def test_password_max_length(self):
        """Password exceeding 128 chars is rejected."""
        long_pw = "A1" + "x" * 127  # 129 chars
        with pytest.raises(ValidationError, match="128"):
            AdminUserCreate(email="a@b.com", password=long_pw)

    def test_first_name_max_length(self):
        """first_name exceeding 255 chars is rejected."""
        long_name = "A" * 256
        with pytest.raises(ValidationError, match="255"):
            AdminUserCreate(
                email="a@b.com",
                password="Secret123",  # pragma: allowlist secret
                first_name=long_name,
            )
