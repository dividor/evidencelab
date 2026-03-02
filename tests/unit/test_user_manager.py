"""Unit tests for UserManager (password validation, account lockout, audit)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi_users import exceptions as fu_exceptions

from ui.backend.auth.users import LOCKOUT_THRESHOLD, UserManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    *,
    email="user@example.com",
    hashed_password="hashed",  # pragma: allowlist secret
    failed_login_attempts=0,
    locked_until=None,
):
    """Create a mock User object for testing."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.hashed_password = hashed_password
    user.failed_login_attempts = failed_login_attempts
    user.locked_until = locked_until
    return user


def _make_credentials(
    username="user@example.com",
    password="Passw0rd!",  # pragma: allowlist secret
):
    """Create a mock credentials object."""
    creds = MagicMock()
    creds.username = username
    creds.password = password
    return creds


def _make_manager():
    """Create a UserManager with a mock user_db."""
    user_db = AsyncMock()
    manager = UserManager(user_db)
    # Mock the password helper
    manager.password_helper = MagicMock()
    return manager


# ---------------------------------------------------------------------------
# Password validation tests
# ---------------------------------------------------------------------------


class TestPasswordValidation:
    """Tests for UserManager.validate_password."""

    @pytest.mark.asyncio
    async def test_rejects_short_password(self):
        """Passwords shorter than MIN_PASSWORD_LENGTH are rejected."""
        manager = _make_manager()
        user = _make_user()
        with pytest.raises(fu_exceptions.InvalidPasswordException) as exc:
            await manager.validate_password("Ab1", user)
        assert "at least" in str(exc.value.reason)

    @pytest.mark.asyncio
    async def test_rejects_password_without_digit(self):
        """Passwords without a digit are rejected."""
        manager = _make_manager()
        user = _make_user()
        with pytest.raises(fu_exceptions.InvalidPasswordException) as exc:
            await manager.validate_password("Abcdefgh", user)
        assert "digit" in str(exc.value.reason)

    @pytest.mark.asyncio
    async def test_rejects_password_without_letter(self):
        """Passwords without a letter are rejected."""
        manager = _make_manager()
        user = _make_user()
        with pytest.raises(fu_exceptions.InvalidPasswordException) as exc:
            await manager.validate_password("12345678", user)
        assert "letter" in str(exc.value.reason)

    @pytest.mark.asyncio
    async def test_accepts_valid_password(self):
        """A password meeting all criteria should be accepted."""
        manager = _make_manager()
        user = _make_user()
        # Should not raise
        pw = "Secure1Pass"  # pragma: allowlist secret
        await manager.validate_password(pw, user)

    @pytest.mark.asyncio
    async def test_rejects_disallowed_email_domain(self):
        """When ALLOWED_EMAIL_DOMAINS is set, reject non-matching domains on registration."""
        from fastapi_users.schemas import BaseUserCreate

        manager = _make_manager()
        # Use a schema object (registration path) — not an ORM model
        schema_user = BaseUserCreate(
            email="user@evil.com",
            password="Secure1Pass",  # pragma: allowlist secret
        )
        with patch(
            "ui.backend.auth.users.ALLOWED_EMAIL_DOMAINS",
            frozenset({"example.com", "corp.org"}),
        ):
            with pytest.raises(fu_exceptions.InvalidPasswordException) as exc:
                pw = "Secure1Pass"  # pragma: allowlist secret
                await manager.validate_password(pw, schema_user)
            assert "restricted" in str(exc.value.reason).lower()

    @pytest.mark.asyncio
    async def test_allows_matching_email_domain(self):
        """When ALLOWED_EMAIL_DOMAINS is set, matching domains are accepted."""
        from fastapi_users.schemas import BaseUserCreate

        manager = _make_manager()
        schema_user = BaseUserCreate(
            email="user@corp.org",
            password="Secure1Pass",  # pragma: allowlist secret
        )
        with patch(
            "ui.backend.auth.users.ALLOWED_EMAIL_DOMAINS",
            frozenset({"example.com", "corp.org"}),
        ):
            pw = "Secure1Pass"  # pragma: allowlist secret
            await manager.validate_password(pw, schema_user)

    @pytest.mark.asyncio
    async def test_no_domain_restriction_when_empty(self):
        """When ALLOWED_EMAIL_DOMAINS is empty, any domain is accepted."""
        from fastapi_users.schemas import BaseUserCreate

        manager = _make_manager()
        schema_user = BaseUserCreate(
            email="user@anydomain.io",
            password="Secure1Pass",  # pragma: allowlist secret
        )
        with patch(
            "ui.backend.auth.users.ALLOWED_EMAIL_DOMAINS",
            frozenset(),
        ):
            pw = "Secure1Pass"  # pragma: allowlist secret
            await manager.validate_password(pw, schema_user)

    @pytest.mark.asyncio
    async def test_minimum_length_is_configurable(self):
        """MIN_PASSWORD_LENGTH should control the minimum."""
        manager = _make_manager()
        user = _make_user()
        short_pw = "Abcde12345"  # pragma: allowlist secret
        with patch("ui.backend.auth.users.MIN_PASSWORD_LENGTH", 12):
            # 10 chars should fail with min=12
            with pytest.raises(fu_exceptions.InvalidPasswordException):
                await manager.validate_password(short_pw, user)


# ---------------------------------------------------------------------------
# Account lockout tests
# ---------------------------------------------------------------------------


class TestAccountLockout:
    """Tests for UserManager.authenticate with lockout logic."""

    @pytest.mark.asyncio
    async def test_successful_login_resets_counters(self):
        """On success, failed_login_attempts should reset to 0."""
        manager = _make_manager()
        user = _make_user(failed_login_attempts=3)
        creds = _make_credentials()

        manager.get_by_email = AsyncMock(return_value=user)
        manager.password_helper.verify_and_update.return_value = (True, None)

        with patch("ui.backend.auth.users.write_audit_event", new_callable=AsyncMock):
            result = await manager.authenticate(creds)

        assert result is user
        # Verify counter was reset
        manager.user_db.update.assert_called_once()
        update_dict = manager.user_db.update.call_args[0][1]
        assert update_dict["failed_login_attempts"] == 0
        assert update_dict["locked_until"] is None

    @pytest.mark.asyncio
    async def test_failed_login_increments_counter(self):
        """Failed login should increment failed_login_attempts."""
        manager = _make_manager()
        user = _make_user(failed_login_attempts=0)
        creds = _make_credentials()

        manager.get_by_email = AsyncMock(return_value=user)
        manager.password_helper.verify_and_update.return_value = (False, None)

        with patch("ui.backend.auth.users.write_audit_event", new_callable=AsyncMock):
            result = await manager.authenticate(creds)

        assert result is None
        manager.user_db.update.assert_called_once()
        update_dict = manager.user_db.update.call_args[0][1]
        assert update_dict["failed_login_attempts"] == 1

    @pytest.mark.asyncio
    async def test_account_locked_after_threshold(self):
        """After LOCKOUT_THRESHOLD failures, the account should be locked."""
        manager = _make_manager()
        user = _make_user(failed_login_attempts=LOCKOUT_THRESHOLD - 1)
        creds = _make_credentials()

        manager.get_by_email = AsyncMock(return_value=user)
        manager.password_helper.verify_and_update.return_value = (False, None)

        with patch("ui.backend.auth.users.write_audit_event", new_callable=AsyncMock):
            result = await manager.authenticate(creds)

        assert result is None
        update_dict = manager.user_db.update.call_args[0][1]
        assert update_dict["failed_login_attempts"] == LOCKOUT_THRESHOLD
        assert "locked_until" in update_dict
        # Lock should be in the future
        assert update_dict["locked_until"] > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_locked_account_rejects_login(self):
        """A locked account should reject login even with correct password."""
        manager = _make_manager()
        lock_time = datetime.now(timezone.utc) + timedelta(minutes=10)
        user = _make_user(locked_until=lock_time)
        creds = _make_credentials()

        manager.get_by_email = AsyncMock(return_value=user)

        with patch("ui.backend.auth.users.write_audit_event", new_callable=AsyncMock):
            result = await manager.authenticate(creds)

        assert result is None
        # Password verification should still run (timing attack mitigation)
        manager.password_helper.hash.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_lockout_allows_login(self):
        """If the lockout has expired, the user should be able to log in."""
        manager = _make_manager()
        # Lock expired 5 minutes ago
        expired_lock = datetime.now(timezone.utc) - timedelta(minutes=5)
        user = _make_user(
            failed_login_attempts=LOCKOUT_THRESHOLD,
            locked_until=expired_lock,
        )
        creds = _make_credentials()

        manager.get_by_email = AsyncMock(return_value=user)
        manager.password_helper.verify_and_update.return_value = (True, None)

        with patch("ui.backend.auth.users.write_audit_event", new_callable=AsyncMock):
            result = await manager.authenticate(creds)

        assert result is user

    @pytest.mark.asyncio
    async def test_nonexistent_user_hashes_password(self):
        """For non-existent users, still hash the password (timing attack mitigation)."""
        manager = _make_manager()
        creds = _make_credentials(username="unknown@test.com")

        manager.get_by_email = AsyncMock(side_effect=fu_exceptions.UserNotExists())

        with patch("ui.backend.auth.users.write_audit_event", new_callable=AsyncMock):
            result = await manager.authenticate(creds)

        assert result is None
        manager.password_helper.hash.assert_called_once_with(creds.password)


# ---------------------------------------------------------------------------
# Audit logging integration tests
# ---------------------------------------------------------------------------


class TestAuthenticateAuditLogging:
    """Tests that authenticate() writes the correct audit events."""

    @pytest.mark.asyncio
    async def test_logs_login_success(self):
        """Successful login should log a login_success event."""
        manager = _make_manager()
        user = _make_user()
        creds = _make_credentials()

        manager.get_by_email = AsyncMock(return_value=user)
        manager.password_helper.verify_and_update.return_value = (True, None)

        with patch(
            "ui.backend.auth.users.write_audit_event", new_callable=AsyncMock
        ) as mock_audit:
            await manager.authenticate(creds)
            # Should have logged login_success
            calls = [c[0][0] for c in mock_audit.call_args_list]
            assert "login_success" in calls

    @pytest.mark.asyncio
    async def test_logs_login_failure(self):
        """Failed login should log a login_failure event."""
        manager = _make_manager()
        user = _make_user()
        creds = _make_credentials()

        manager.get_by_email = AsyncMock(return_value=user)
        manager.password_helper.verify_and_update.return_value = (False, None)

        with patch(
            "ui.backend.auth.users.write_audit_event", new_callable=AsyncMock
        ) as mock_audit:
            await manager.authenticate(creds)
            calls = [c[0][0] for c in mock_audit.call_args_list]
            assert "login_failure" in calls

    @pytest.mark.asyncio
    async def test_logs_login_locked(self):
        """Locked account login should log a login_locked event."""
        manager = _make_manager()
        lock_time = datetime.now(timezone.utc) + timedelta(minutes=10)
        user = _make_user(locked_until=lock_time)
        creds = _make_credentials()

        manager.get_by_email = AsyncMock(return_value=user)

        with patch(
            "ui.backend.auth.users.write_audit_event", new_callable=AsyncMock
        ) as mock_audit:
            await manager.authenticate(creds)
            calls = [c[0][0] for c in mock_audit.call_args_list]
            assert "login_locked" in calls

    @pytest.mark.asyncio
    async def test_logs_user_not_found(self):
        """Non-existent user login should log login_failure."""
        manager = _make_manager()
        creds = _make_credentials(username="nobody@test.com")

        manager.get_by_email = AsyncMock(side_effect=fu_exceptions.UserNotExists())

        with patch(
            "ui.backend.auth.users.write_audit_event", new_callable=AsyncMock
        ) as mock_audit:
            await manager.authenticate(creds)
            calls = [c[0][0] for c in mock_audit.call_args_list]
            assert "login_failure" in calls
            # Check that user_email is recorded
            call_kwargs = mock_audit.call_args_list[0][1]
            assert call_kwargs["user_email"] == "nobody@test.com"


# ---------------------------------------------------------------------------
# AUTH_SECRET validation tests
# ---------------------------------------------------------------------------


class TestAuthSecretValidation:
    """Tests for AUTH_SECRET_KEY validation logic."""

    def test_insecure_secret_generates_ephemeral(self):
        """Insecure or missing AUTH_SECRET_KEY should generate a random one."""
        env = {"AUTH_SECRET_KEY": "changeme"}  # pragma: allowlist secret
        with patch.dict("os.environ", env):
            import importlib

            import ui.backend.auth.users as mod

            importlib.reload(mod)
            # The secret should NOT be the insecure default
            assert mod.AUTH_SECRET != "changeme"  # pragma: allowlist secret
            assert len(mod.AUTH_SECRET) >= 32

    def test_short_secret_generates_ephemeral(self):
        """AUTH_SECRET_KEY shorter than 32 chars triggers regeneration."""
        env = {"AUTH_SECRET_KEY": "tooshort"}  # pragma: allowlist secret
        with patch.dict("os.environ", env):
            import importlib

            import ui.backend.auth.users as mod

            importlib.reload(mod)
            assert mod.AUTH_SECRET != "tooshort"  # pragma: allowlist secret
            assert len(mod.AUTH_SECRET) >= 32

    def test_valid_secret_used_directly(self):
        """A sufficiently long, non-default secret is used as-is."""
        good_secret = "a" * 64  # pragma: allowlist secret
        with patch.dict("os.environ", {"AUTH_SECRET_KEY": good_secret}):
            import importlib

            import ui.backend.auth.users as mod

            importlib.reload(mod)
            assert mod.AUTH_SECRET == good_secret


# ---------------------------------------------------------------------------
# Password reset lockout-clear tests
# ---------------------------------------------------------------------------


class TestPasswordResetClearsLockout:
    """Tests that on_after_reset_password resets lockout counters."""

    @pytest.mark.asyncio
    async def test_reset_password_clears_lockout(self):
        """After password reset, failed_login_attempts and locked_until are cleared."""
        manager = _make_manager()
        user = _make_user(
            failed_login_attempts=LOCKOUT_THRESHOLD,
            locked_until=datetime.now(timezone.utc) + timedelta(minutes=10),
        )

        mock_session = AsyncMock()
        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.1"

        with (
            patch(
                "ui.backend.auth.users.get_async_session",
            ) as mock_get_session,
            patch(
                "ui.backend.auth.users.write_audit_event",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            # Make get_async_session yield a mock session
            async def _session_gen():
                yield mock_session

            mock_get_session.return_value = _session_gen()

            await manager.on_after_reset_password(user, mock_request)

            # Session should have executed a statement and committed
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

            # Audit event should be written
            mock_audit.assert_called_once()
            assert mock_audit.call_args[0][0] == "password_reset_success"
            assert mock_audit.call_args[1]["user_id"] == user.id

    @pytest.mark.asyncio
    async def test_reset_password_logs_ip(self):
        """Password reset audit event should include the client IP."""
        manager = _make_manager()
        user = _make_user()

        mock_session = AsyncMock()
        mock_request = MagicMock()
        mock_request.client.host = "10.0.0.1"

        with (
            patch(
                "ui.backend.auth.users.get_async_session",
            ) as mock_get_session,
            patch(
                "ui.backend.auth.users.write_audit_event",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):

            async def _session_gen():
                yield mock_session

            mock_get_session.return_value = _session_gen()

            await manager.on_after_reset_password(user, mock_request)

            assert mock_audit.call_args[1]["ip_address"] == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_reset_password_handles_no_request(self):
        """Password reset should handle missing request gracefully."""
        manager = _make_manager()
        user = _make_user()

        mock_session = AsyncMock()

        with (
            patch(
                "ui.backend.auth.users.get_async_session",
            ) as mock_get_session,
            patch(
                "ui.backend.auth.users.write_audit_event",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):

            async def _session_gen():
                yield mock_session

            mock_get_session.return_value = _session_gen()

            await manager.on_after_reset_password(user, None)

            assert mock_audit.call_args[1]["ip_address"] == "unknown"


# ---------------------------------------------------------------------------
# Domain check: registration-only (not password change)
# ---------------------------------------------------------------------------


class TestDomainCheckRegistrationOnly:
    """Domain whitelist should only be enforced during registration."""

    @pytest.mark.asyncio
    async def test_domain_check_enforced_on_schema(self):
        """Domain check runs when user is a BaseUserCreate schema (registration)."""
        from fastapi_users.schemas import BaseUserCreate

        manager = _make_manager()
        schema_user = BaseUserCreate(
            email="user@evil.com",
            password="Secure1Pass",  # pragma: allowlist secret
        )
        with patch(
            "ui.backend.auth.users.ALLOWED_EMAIL_DOMAINS",
            frozenset({"example.com"}),
        ):
            with pytest.raises(fu_exceptions.InvalidPasswordException) as exc:
                pw = "Secure1Pass"  # pragma: allowlist secret
                await manager.validate_password(pw, schema_user)
            assert "restricted" in str(exc.value.reason).lower()

    @pytest.mark.asyncio
    async def test_domain_check_skipped_on_orm_model(self):
        """Domain check should NOT run when user is an ORM model (password change)."""
        manager = _make_manager()
        # ORM model (MagicMock) is not isinstance of BaseUserCreate
        orm_user = _make_user(email="user@evil.com")
        with patch(
            "ui.backend.auth.users.ALLOWED_EMAIL_DOMAINS",
            frozenset({"example.com"}),
        ):
            # Should NOT raise — domain check skipped for ORM model
            pw = "Secure1Pass"  # pragma: allowlist secret
            await manager.validate_password(pw, orm_user)


# ---------------------------------------------------------------------------
# Token lifetime configuration tests
# ---------------------------------------------------------------------------


class TestTokenLifetimeConfiguration:
    """Tests for configurable token lifetimes."""

    def test_reset_token_lifetime_configurable(self):
        """AUTH_RESET_TOKEN_LIFETIME should control reset token lifetime."""
        env = {
            "AUTH_RESET_TOKEN_LIFETIME": "3600",
            "AUTH_SECRET_KEY": "a" * 64,  # pragma: allowlist secret
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.users as mod

            importlib.reload(mod)
            assert mod.RESET_PASSWORD_TOKEN_LIFETIME == 3600

    def test_verify_token_lifetime_configurable(self):
        """AUTH_VERIFY_TOKEN_LIFETIME should control verify token lifetime."""
        env = {
            "AUTH_VERIFY_TOKEN_LIFETIME": "172800",
            "AUTH_SECRET_KEY": "a" * 64,  # pragma: allowlist secret
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.users as mod

            importlib.reload(mod)
            assert mod.VERIFY_TOKEN_LIFETIME == 172800

    def test_reset_token_default_24_hours(self):
        """Default reset token lifetime should be 86400 seconds (24 hours)."""
        env = {"AUTH_SECRET_KEY": "a" * 64}  # pragma: allowlist secret
        with patch.dict("os.environ", env, clear=False):
            import os

            os.environ.pop("AUTH_RESET_TOKEN_LIFETIME", None)
            import importlib

            import ui.backend.auth.users as mod

            importlib.reload(mod)
            assert mod.RESET_PASSWORD_TOKEN_LIFETIME == 86400

    def test_verify_token_default_7_days(self):
        """Default verify token lifetime should be 604800 seconds (7 days)."""
        env = {"AUTH_SECRET_KEY": "a" * 64}  # pragma: allowlist secret
        with patch.dict("os.environ", env, clear=False):
            import os

            os.environ.pop("AUTH_VERIFY_TOKEN_LIFETIME", None)
            import importlib

            import ui.backend.auth.users as mod

            importlib.reload(mod)
            assert mod.VERIFY_TOKEN_LIFETIME == 604800

    def test_user_manager_uses_configured_lifetimes(self):
        """UserManager class should use the configured token lifetimes."""
        manager = _make_manager()
        # These should be set from the module-level constants
        from ui.backend.auth.users import (
            RESET_PASSWORD_TOKEN_LIFETIME,
            VERIFY_TOKEN_LIFETIME,
        )

        assert (
            manager.reset_password_token_lifetime_seconds
            == RESET_PASSWORD_TOKEN_LIFETIME
        )
        assert manager.verification_token_lifetime_seconds == VERIFY_TOKEN_LIFETIME
