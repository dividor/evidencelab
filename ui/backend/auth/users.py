"""fastapi-users configuration: UserManager, auth backends, dependency factories."""

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users import exceptions as fu_exceptions
from fastapi_users import schemas as fu_schemas
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.audit import write_audit_event
from ui.backend.auth.db import get_async_session
from ui.backend.auth.email import (
    password_reset_email_html,
    send_email,
    verification_email_html,
)
from ui.backend.auth.models import OAuthAccount, User
from ui.backend.auth.rate_limit import current_request_ip
from ui.backend.services.permissions import add_user_to_default_group

logger = logging.getLogger(__name__)

_INSECURE_DEFAULTS = frozenset(
    {
        "CHANGE-ME-IN-PRODUCTION",
        "changeme-generate-a-real-secret",
        "changeme",
        "secret",
        "",
    }
)

AUTH_SECRET = os.environ.get("AUTH_SECRET_KEY", "")
if AUTH_SECRET in _INSECURE_DEFAULTS or len(AUTH_SECRET) < 32:
    _generated = secrets.token_hex(32)
    logger.critical(
        "AUTH_SECRET_KEY is missing or insecure (len=%d). "
        "Set AUTH_SECRET_KEY to a random 32+ character string "
        "(e.g. `openssl rand -hex 32`). "
        "A random ephemeral secret has been generated for this process — "
        "tokens will NOT survive restarts.",
        len(AUTH_SECRET),
    )
    AUTH_SECRET = _generated

TOKEN_LIFETIME_SECONDS = 3600  # 1 hour (short-lived; refresh via cookie)

# Registration controls — restrict who can sign up.
# Comma-separated list of allowed email domains (e.g. "example.com,corp.org").
# Empty string means open registration (anyone can register).
_ALLOWED_DOMAINS_RAW = os.environ.get("AUTH_ALLOWED_EMAIL_DOMAINS", "")
ALLOWED_EMAIL_DOMAINS: frozenset[str] = frozenset(
    d.strip().lower() for d in _ALLOWED_DOMAINS_RAW.split(",") if d.strip()
)

# Minimum password length enforced at the backend (defence-in-depth).
MIN_PASSWORD_LENGTH = int(os.environ.get("AUTH_MIN_PASSWORD_LENGTH", "12"))

# Account lockout — lock after N consecutive failures for M minutes.
LOCKOUT_THRESHOLD = int(os.environ.get("AUTH_LOCKOUT_THRESHOLD", "5"))
LOCKOUT_DURATION_MINUTES = int(os.environ.get("AUTH_LOCKOUT_DURATION_MINUTES", "15"))

# Password history — prevent reuse of the last N passwords (ASVS V2.1.10).
PASSWORD_HISTORY_COUNT = int(os.environ.get("AUTH_PASSWORD_HISTORY_COUNT", "5"))

# Token lifetimes for password reset and email verification.
# These are independent of the JWT access token lifetime (1 hour).
RESET_PASSWORD_TOKEN_LIFETIME = int(
    os.environ.get("AUTH_RESET_TOKEN_LIFETIME", "3600")  # 1 hour (ASVS V2.5.2)
)
VERIFY_TOKEN_LIFETIME = int(
    os.environ.get("AUTH_VERIFY_TOKEN_LIFETIME", "86400")  # 24 hours (ASVS V2.3.2)
)


# ---------------------------------------------------------------------------
# User database adapter
# ---------------------------------------------------------------------------


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> SQLAlchemyUserDatabase:
    """Yield a fastapi-users SQLAlchemy database adapter."""
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


# ---------------------------------------------------------------------------
# UserManager — customises registration, verification, etc.
# ---------------------------------------------------------------------------


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Custom user manager with email verification and password reset."""

    reset_password_token_secret = AUTH_SECRET
    reset_password_token_lifetime_seconds = RESET_PASSWORD_TOKEN_LIFETIME
    verification_token_secret = AUTH_SECRET
    verification_token_lifetime_seconds = VERIFY_TOKEN_LIFETIME

    # ------------------------------------------------------------------
    # Account lockout — override authenticate to track failures
    # ------------------------------------------------------------------

    async def authenticate(  # type: ignore[override]
        self, credentials
    ) -> Optional[User]:
        """Authenticate with account lockout and audit logging."""
        ip = current_request_ip.get("unknown")

        try:
            user = await self.get_by_email(credentials.username)
        except fu_exceptions.UserNotExists:
            # Timing-attack mitigation: still run the hasher
            self.password_helper.hash(credentials.password)
            await write_audit_event(
                "login_failure",
                user_email=credentials.username,
                ip_address=ip,
                details={"reason": "user_not_found"},
            )
            return None

        # Check lockout
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            self.password_helper.hash(credentials.password)
            logger.warning("Login blocked — account locked: %s", user.email)
            await write_audit_event(
                "login_locked",
                user_id=user.id,
                user_email=user.email,
                ip_address=ip,
            )
            return None

        verified, updated_password_hash = self.password_helper.verify_and_update(
            credentials.password, user.hashed_password
        )

        if not verified:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            update_dict: dict = {
                "failed_login_attempts": user.failed_login_attempts,
            }
            if user.failed_login_attempts >= LOCKOUT_THRESHOLD:
                lock_until = datetime.now(timezone.utc) + timedelta(
                    minutes=LOCKOUT_DURATION_MINUTES
                )
                update_dict["locked_until"] = lock_until
                logger.warning(
                    "Account locked (%d failures): %s",
                    user.failed_login_attempts,
                    user.email,
                )
            await self.user_db.update(user, update_dict)
            await write_audit_event(
                "login_failure",
                user_id=user.id,
                user_email=user.email,
                ip_address=ip,
                details={"attempt": user.failed_login_attempts},
            )
            return None

        # Success — reset lockout counters
        update_dict = {}
        if user.failed_login_attempts:
            update_dict["failed_login_attempts"] = 0
            update_dict["locked_until"] = None
        if updated_password_hash is not None:
            update_dict["hashed_password"] = updated_password_hash
        if update_dict:
            await self.user_db.update(user, update_dict)

        # Block email-registered users who haven't verified their address.
        # OAuth users bypass this method entirely (they use the OAuth flow).
        if not user.is_verified:
            logger.info("Login denied — email not verified: %s", user.email)
            await write_audit_event(
                "login_failure",
                user_id=user.id,
                user_email=user.email,
                ip_address=ip,
                details={"reason": "email_not_verified"},
            )
            raise HTTPException(
                status_code=400,
                detail="Please verify your email address before signing in. "
                "Check your inbox for the verification link.",
            )

        await write_audit_event(
            "login_success",
            user_id=user.id,
            user_email=user.email,
            ip_address=ip,
        )
        return user

    # ------------------------------------------------------------------
    # Password validation
    # ------------------------------------------------------------------

    def _check_password_history(self, password: str, user: User) -> None:
        """Raise if *password* matches any recent hash on *user* (ASVS V2.1.10)."""
        reuse_msg = f"Cannot reuse any of your last {PASSWORD_HISTORY_COUNT} passwords."
        # Check current password
        if hasattr(user, "hashed_password") and user.hashed_password:
            matched, _ = self.password_helper.verify_and_update(
                password, user.hashed_password
            )
            if matched:
                raise fu_exceptions.InvalidPasswordException(reason=reuse_msg)
        # Check stored history
        history = getattr(user, "password_history", None) or []
        for old_hash in history[-PASSWORD_HISTORY_COUNT:]:
            matched, _ = self.password_helper.verify_and_update(password, old_hash)
            if matched:
                raise fu_exceptions.InvalidPasswordException(reason=reuse_msg)

    async def validate_password(
        self, password: str, user: User  # type: ignore[override]
    ) -> None:
        """Enforce password length, history, and email domain restrictions.

        Raises:
            InvalidPasswordException: If validation fails.
        """
        if len(password) < MIN_PASSWORD_LENGTH:
            raise fu_exceptions.InvalidPasswordException(
                reason=f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )

        # Password history — only on password change (ORM model), not registration.
        if PASSWORD_HISTORY_COUNT > 0 and not isinstance(
            user, fu_schemas.BaseUserCreate
        ):
            self._check_password_history(password, user)

        # Domain whitelist — only on registration (not password change).
        if ALLOWED_EMAIL_DOMAINS and isinstance(user, fu_schemas.BaseUserCreate):
            domain = user.email.rsplit("@", 1)[-1].lower()
            if domain not in ALLOWED_EMAIL_DOMAINS:
                raise fu_exceptions.InvalidPasswordException(
                    reason="Registration is restricted to approved email domains."
                )

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Add user to default group and send verification email."""
        # Add to default group so new users have baseline access
        async for session in get_async_session():
            await add_user_to_default_group(session, user.id)
        ip = request.client.host if request and request.client else "unknown"
        await write_audit_event(
            "register", user_id=user.id, user_email=user.email, ip_address=ip
        )

        # When email confirmation is disabled, auto-verify the account so the
        # user can log in immediately without an SMTP server.
        if os.environ.get("DISABLE_EMAIL_CONFIRMATION", "").lower() == "true":
            logger.warning(
                "DISABLE_EMAIL_CONFIRMATION=true — auto-verifying %s",
                user.email,
            )
            async for session in get_async_session():
                await session.execute(
                    update(User).where(User.id == user.id).values(is_verified=True)
                )
                await session.commit()
            return

        await self.request_verify(user, request)

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Send the verification token by email."""
        base_url = os.environ.get("APP_BASE_URL", "http://localhost:3000")
        verify_url = f"{base_url}?verify={token}"
        await send_email(
            to=user.email,
            subject="Verify your Evidence Lab account",
            body_html=verification_email_html(verify_url),
        )

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Send a password reset link by email."""
        ip = request.client.host if request and request.client else "unknown"
        await write_audit_event(
            "password_reset_request",
            user_id=user.id,
            user_email=user.email,
            ip_address=ip,
        )
        base_url = os.environ.get("APP_BASE_URL", "http://localhost:3000")
        reset_url = f"{base_url}?reset-password={token}"
        await send_email(
            to=user.email,
            subject="Reset your Evidence Lab password",
            body_html=password_reset_email_html(reset_url),
        )

    async def on_after_reset_password(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Reset lockout counters and record password history."""
        # Push the old password hash into the history list (ASVS V2.1.10)
        history = (
            list(user.password_history or [])
            if hasattr(user, "password_history")
            else []
        )
        if user.hashed_password:
            history.append(user.hashed_password)
        # Keep only the last N entries
        history = (
            history[-PASSWORD_HISTORY_COUNT:] if PASSWORD_HISTORY_COUNT > 0 else []
        )

        async for session in get_async_session():
            stmt = (
                update(User)
                .where(User.id == user.id)
                .values(
                    failed_login_attempts=0,
                    locked_until=None,
                    password_history=history,
                )
            )
            await session.execute(stmt)
            await session.commit()
        ip = request.client.host if request and request.client else "unknown"
        await write_audit_event(
            "password_reset_success",
            user_id=user.id,
            user_email=user.email,
            ip_address=ip,
        )


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    """Dependency that yields a UserManager instance."""
    yield UserManager(user_db)


# ---------------------------------------------------------------------------
# Authentication backends (JWT via Bearer header + cookie)
# ---------------------------------------------------------------------------


def get_jwt_strategy() -> JWTStrategy:
    """Create a JWT strategy with the configured secret."""
    return JWTStrategy(secret=AUTH_SECRET, lifetime_seconds=TOKEN_LIFETIME_SECONDS)


bearer_transport = BearerTransport(tokenUrl="auth/login")
cookie_transport = CookieTransport(
    cookie_max_age=TOKEN_LIFETIME_SECONDS,
    cookie_name="evidencelab_auth",
    cookie_httponly=True,
    cookie_secure=os.environ.get("AUTH_COOKIE_SECURE", "true").lower() != "false",
    cookie_samesite="lax",
)

bearer_backend = AuthenticationBackend(
    name="jwt-bearer",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

cookie_backend = AuthenticationBackend(
    name="jwt-cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

# ---------------------------------------------------------------------------
# FastAPIUsers instance — provides router factories and current_user deps
# ---------------------------------------------------------------------------

fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [bearer_backend, cookie_backend],
)

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
optional_current_user = fastapi_users.current_user(active=True, optional=True)
