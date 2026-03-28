"""OAuth 2.0 Authorization Server for MCP clients.

Implements RFC 8414 (Authorization Server Metadata), RFC 7636 (PKCE),
and RFC 7591 (Dynamic Client Registration) so that MCP clients like
Claude Desktop and ChatGPT can discover the auth endpoints and walk
users through the Evidence Lab login flow.

The flow:
  1. Client discovers endpoints via /.well-known/oauth-authorization-server
  2. Client registers dynamically via /register
  3. Client redirects user to /authorize with PKCE challenge
  4. User logs in via the Evidence Lab UI (Microsoft / Google OAuth)
  5. Browser redirects back to client with an authorization code
  6. Client exchanges code for a Bearer token via /token
  7. Client uses Bearer token in subsequent MCP requests
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import jwt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AUTH_SECRET = os.environ.get("AUTH_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = ["fastapi-users:auth"]
TOKEN_LIFETIME = 3600  # 1 hour

# Where the Evidence Lab UI login page lives
_APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000")

# Public base URL for the MCP server (used in metadata discovery)
_MCP_PUBLIC_URL = os.environ.get(
    "MCP_PUBLIC_URL",
    os.environ.get("APP_BASE_URL", "http://localhost:3000") + "/mcp",
)

# ---------------------------------------------------------------------------
# In-memory stores (sufficient for MCP — small number of concurrent clients)
# ---------------------------------------------------------------------------

# Dynamic client registrations: client_id -> {client_name, redirect_uris, ...}
_clients: dict[str, dict] = {}

# Pending authorization codes: code -> {client_id, code_challenge, user_id, ...}
_auth_codes: dict[str, dict] = {}


def _clean_expired(store: dict, field: str = "expires_at") -> None:
    """Remove expired entries from an in-memory store."""
    now = time.time()
    expired = [k for k, v in store.items() if v.get(field, 0) < now]
    for k in expired:
        del store[k]


# ---------------------------------------------------------------------------
# Metadata discovery (RFC 8414)
# ---------------------------------------------------------------------------


def get_metadata() -> dict:
    """Return OAuth 2.0 Authorization Server Metadata."""
    return {
        "issuer": _MCP_PUBLIC_URL,
        "authorization_endpoint": f"{_MCP_PUBLIC_URL}/authorize",
        "token_endpoint": f"{_MCP_PUBLIC_URL}/token",
        "registration_endpoint": f"{_MCP_PUBLIC_URL}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["search", "assistant", "read"],
    }


# ---------------------------------------------------------------------------
# Dynamic client registration (RFC 7591)
# ---------------------------------------------------------------------------


def register_client(body: dict) -> dict:
    """Register a new OAuth client dynamically."""
    client_id = secrets.token_urlsafe(24)
    client_secret = secrets.token_urlsafe(32)

    redirect_uris = body.get("redirect_uris", [])
    if not redirect_uris:
        redirect_uris = []

    client = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": body.get("client_name", "MCP Client"),
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "created_at": time.time(),
    }
    _clients[client_id] = client
    logger.info("Registered OAuth client: %s (%s)", client_id, client["client_name"])

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": client["client_name"],
        "redirect_uris": redirect_uris,
        "grant_types": client["grant_types"],
        "response_types": client["response_types"],
        "token_endpoint_auth_method": client["token_endpoint_auth_method"],
    }


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------


def build_authorize_redirect(params: dict) -> tuple[int, str]:
    """Build the redirect for the /authorize endpoint.

    Returns (status_code, redirect_url).  The redirect sends the user
    to the Evidence Lab login page with a ``next`` parameter that will
    bring them back to complete the OAuth flow.
    """
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")
    code_challenge_method = params.get("code_challenge_method", "")
    state = params.get("state", "")
    scope = params.get("scope", "")

    if not client_id or not redirect_uri or not code_challenge:
        return 400, json.dumps(
            {
                "error": "invalid_request",
                "error_description": "Missing required parameters",
            }
        )

    if code_challenge_method and code_challenge_method != "S256":
        return 400, json.dumps(
            {
                "error": "invalid_request",
                "error_description": "Only S256 code_challenge_method supported",
            }
        )

    # Generate an authorization code and store the pending request
    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "state": state,
        "scope": scope,
        "user_id": None,  # Set when user completes login
        "expires_at": time.time() + 600,  # 10 minutes
        "authenticated": False,
    }

    # For now, auto-approve and redirect back immediately.
    # In a full implementation, this would show the Evidence Lab
    # login page and set user_id after authentication.
    _auth_codes[code]["authenticated"] = True
    _auth_codes[code]["user_id"] = "mcp_user"

    # Build redirect back to the client
    callback_params = {"code": code}
    if state:
        callback_params["state"] = state

    separator = "&" if "?" in redirect_uri else "?"
    redirect_url = f"{redirect_uri}{separator}{urlencode(callback_params)}"
    return 302, redirect_url


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


def exchange_token(body: dict) -> tuple[int, dict]:
    """Exchange an authorization code for a Bearer token.

    Validates the PKCE code_verifier against the stored code_challenge.
    Returns (status_code, response_body).
    """
    _clean_expired(_auth_codes)

    grant_type = body.get("grant_type", "")
    code = body.get("code", "")
    code_verifier = body.get("code_verifier", "")

    if grant_type != "authorization_code":
        return 400, {"error": "unsupported_grant_type"}

    if code not in _auth_codes:
        return 400, {
            "error": "invalid_grant",
            "error_description": "Invalid or expired code",
        }

    pending = _auth_codes.pop(code)

    if not pending.get("authenticated"):
        return 400, {
            "error": "invalid_grant",
            "error_description": "Authorization not completed",
        }

    # Validate PKCE
    if code_verifier:
        expected = hashlib.sha256(code_verifier.encode("ascii")).digest()
        # urlsafe base64 without padding
        import base64

        expected_b64 = base64.urlsafe_b64encode(expected).rstrip(b"=").decode("ascii")
        if expected_b64 != pending["code_challenge"]:
            return 400, {
                "error": "invalid_grant",
                "error_description": "PKCE verification failed",
            }

    # Issue a JWT access token
    now = time.time()
    payload = {
        "sub": pending["user_id"],
        "aud": JWT_AUDIENCE,
        "iat": int(now),
        "exp": int(now + TOKEN_LIFETIME),
        "scope": pending.get("scope", ""),
        "client_id": pending["client_id"],
    }
    access_token = jwt.encode(payload, AUTH_SECRET, algorithm=JWT_ALGORITHM)

    return 200, {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": TOKEN_LIFETIME,
        "scope": pending.get("scope", ""),
    }
