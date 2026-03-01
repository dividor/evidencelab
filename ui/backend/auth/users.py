"""fastapi-users configuration: UserManager, auth backends, dependency factories."""

import os
import uuid
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.email import send_email
from ui.backend.auth.models import OAuthAccount, User

AUTH_SECRET = os.environ.get("AUTH_SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
TOKEN_LIFETIME_SECONDS = 3600 * 24  # 24 hours


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
    verification_token_secret = AUTH_SECRET

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Send verification email after registration."""
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
            body_html=(
                f"<p>Welcome to Evidence Lab!</p>"
                f'<p>Please <a href="{verify_url}">click here to verify your email</a>.</p>'
                f"<p>Or paste this link in your browser: {verify_url}</p>"
            ),
        )

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Send a password reset link by email."""
        base_url = os.environ.get("APP_BASE_URL", "http://localhost:3000")
        reset_url = f"{base_url}?reset-password={token}"
        await send_email(
            to=user.email,
            subject="Reset your Evidence Lab password",
            body_html=(
                f"<p>You requested a password reset.</p>"
                f'<p><a href="{reset_url}">Click here to reset your password</a>.</p>'
                f"<p>Or paste this link in your browser: {reset_url}</p>"
                f"<p>If you didn't request this, ignore this email.</p>"
            ),
        )


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> UserManager:
    """Dependency that yields a UserManager instance."""
    yield UserManager(user_db)


# ---------------------------------------------------------------------------
# Authentication backends (JWT via Bearer header + cookie)
# ---------------------------------------------------------------------------


def get_jwt_strategy() -> JWTStrategy:
    """Create a JWT strategy with the configured secret."""
    return JWTStrategy(secret=AUTH_SECRET, lifetime_seconds=TOKEN_LIFETIME_SECONDS)


bearer_transport = BearerTransport(tokenUrl="auth/login")
cookie_transport = CookieTransport(cookie_max_age=TOKEN_LIFETIME_SECONDS)

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
