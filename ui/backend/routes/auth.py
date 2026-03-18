"""Authentication routes — login, register, verify, OAuth callbacks."""

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from ui.backend.auth.oauth import google_oauth_client, microsoft_oauth_client
from ui.backend.auth.schemas import UserCreate, UserRead
from ui.backend.auth.users import (
    AUTH_SECRET,
    bearer_backend,
    cookie_backend,
    fastapi_users,
    get_user_manager,
)

# Base URL for OAuth callbacks (must be reachable by the browser, not the
# internal Docker hostname).  Falls back to localhost:8000 for local dev.
_OAUTH_CALLBACK_BASE = os.environ.get(
    "OAUTH_CALLBACK_BASE_URL", "http://localhost:8000"
)

# Where to redirect the browser after a successful OAuth login.
_APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000")

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
#
# We use cookie_backend so the auth cookie is set on the callback response.
# The callback response is converted to a redirect back to the app so the
# browser doesn't just display JSON.
# ---------------------------------------------------------------------------


def _make_oauth_router(oauth_client, provider_name: str):
    """Create an OAuth router that sets a cookie and redirects to the app.

    fastapi_users' built-in OAuth callback returns a 204 with the auth
    cookie set.  We wrap it: the /authorize endpoint returns JSON with
    the authorization_url (consumed by the frontend), and the /callback
    endpoint authenticates the user, sets the httpOnly auth cookie, then
    redirects the browser back to the application.
    """
    from fastapi_users.router.oauth import generate_state_token

    oauth_router = APIRouter()

    # --- /authorize --------------------------------------------------------
    @oauth_router.get("/authorize")
    async def authorize(request: Request, scopes: list[str] = Query(None)):
        authorize_redirect_url = f"{_OAUTH_CALLBACK_BASE}/auth/{provider_name}/callback"
        state_data = {"sub": str(request.client.host) if request.client else ""}
        state = generate_state_token(state_data, AUTH_SECRET)
        authorization_url = await oauth_client.get_authorization_url(
            authorize_redirect_url,
            state,
            scopes,
        )
        return {"authorization_url": authorization_url}

    # --- /callback ---------------------------------------------------------
    @oauth_router.get("/callback")
    async def callback(
        request: Request,
        code: str = Query(...),
        state: str = Query(None),
        user_manager=Depends(get_user_manager),
        strategy=Depends(cookie_backend.get_strategy),
    ):
        redirect_url = f"{_OAUTH_CALLBACK_BASE}/auth/{provider_name}/callback"
        # Exchange code for token
        try:
            token = await oauth_client.get_access_token(code, redirect_url)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAUTH_EXCHANGE_ERROR",
            )

        account_id, account_email = await oauth_client.get_id_email(
            token["access_token"]
        )
        if account_email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAUTH_NOT_AVAILABLE_EMAIL",
            )

        # Create or link user
        try:
            user = await user_manager.oauth_callback(
                oauth_client.name,
                token["access_token"],
                account_id,
                account_email,
                token.get("expires_at"),
                token.get("refresh_token"),
                request,
                associate_by_email=True,
                is_verified_by_default=True,
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAUTH_USER_ALREADY_EXISTS",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LOGIN_BAD_CREDENTIALS",
            )

        # Log in via cookie backend — sets the httpOnly auth cookie
        login_response = await cookie_backend.login(strategy, user)

        # Convert to a redirect, preserving the Set-Cookie header
        redirect = RedirectResponse(url=_APP_BASE_URL, status_code=302)
        for header_name, header_value in login_response.raw_headers:
            if header_name.lower() == b"set-cookie":
                redirect.raw_headers.append((header_name, header_value))

        return redirect

    return oauth_router


if google_oauth_client is not None:
    router.include_router(
        _make_oauth_router(google_oauth_client, "google"),
        prefix="/google",
        tags=["auth"],
    )

if microsoft_oauth_client is not None:
    router.include_router(
        _make_oauth_router(microsoft_oauth_client, "microsoft"),
        prefix="/microsoft",
        tags=["auth"],
    )
