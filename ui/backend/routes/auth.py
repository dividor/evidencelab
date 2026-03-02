"""Authentication routes — login, register, verify, OAuth callbacks."""

from fastapi import APIRouter

from ui.backend.auth.oauth import google_oauth_client, microsoft_oauth_client
from ui.backend.auth.schemas import UserCreate, UserRead
from ui.backend.auth.users import (
    AUTH_SECRET,
    bearer_backend,
    cookie_backend,
    fastapi_users,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Email/password auth
# ---------------------------------------------------------------------------

router.include_router(
    fastapi_users.get_auth_router(bearer_backend),
    prefix="/login",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_auth_router(cookie_backend),
    prefix="/cookie-login",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_verify_router(UserRead),
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_reset_password_router(),
    tags=["auth"],
)

# ---------------------------------------------------------------------------
# OAuth providers (only registered when credentials are configured)
# ---------------------------------------------------------------------------

if google_oauth_client is not None:
    router.include_router(
        fastapi_users.get_oauth_router(
            google_oauth_client,
            bearer_backend,
            state_secret=AUTH_SECRET,
            redirect_url=None,  # defaults to {base}/auth/google/callback
            associate_by_email=True,
        ),
        prefix="/google",
        tags=["auth"],
    )

if microsoft_oauth_client is not None:
    router.include_router(
        fastapi_users.get_oauth_router(
            microsoft_oauth_client,
            bearer_backend,
            state_secret=AUTH_SECRET,
            redirect_url=None,
            associate_by_email=True,
        ),
        prefix="/microsoft",
        tags=["auth"],
    )
