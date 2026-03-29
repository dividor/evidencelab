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

Security controls:
  - PKCE (S256) required on all authorization requests
  - redirect_uri validated against registered client URIs (RFC 6749 §10.6)
  - Per-IP rate limiting on /register, /authorize, /token
  - Audit logging for all OAuth events
  - CSRF binding: pending auth tied to session via secure token
  - Short-lived codes (5 min) and tokens (1 hour)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from collections import defaultdict
from urllib.parse import urlencode, urlparse

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

# Rate limiting: max requests per window
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMITS = {
    "register": 10,  # 10 registrations per minute per IP
    "authorize": 20,  # 20 authorize attempts per minute per IP
    "token": 30,  # 30 token exchanges per minute per IP
}

# ---------------------------------------------------------------------------
# In-memory stores (sufficient for MCP — small number of concurrent clients)
# ---------------------------------------------------------------------------

# Dynamic client registrations: client_id -> {client_name, redirect_uris, ...}
_clients: dict[str, dict] = {}

# Pending authorization codes: code -> {client_id, code_challenge, user_id, ...}
_auth_codes: dict[str, dict] = {}

# Rate limiting: (endpoint, ip) -> [timestamps]
_rate_counts: dict[tuple[str, str], list[float]] = defaultdict(list)


def _clean_expired(store: dict, field: str = "expires_at") -> None:
    """Remove expired entries from an in-memory store."""
    now = time.time()
    expired = [k for k, v in store.items() if v.get(field, 0) < now]
    for k in expired:
        del store[k]


def _check_rate_limit(endpoint: str, client_ip: str) -> str | None:
    """Return an error message if the rate limit is exceeded, else None."""
    now = time.time()
    key = (endpoint, client_ip)
    window_start = now - _RATE_LIMIT_WINDOW

    # Prune old entries
    _rate_counts[key] = [t for t in _rate_counts[key] if t > window_start]

    limit = _RATE_LIMITS.get(endpoint, 30)
    if len(_rate_counts[key]) >= limit:
        logger.warning(
            "OAuth rate limit exceeded: endpoint=%s ip=%s count=%d",
            endpoint,
            client_ip,
            len(_rate_counts[key]),
        )
        return f"Rate limit exceeded. Max {limit} requests per {_RATE_LIMIT_WINDOW}s."

    _rate_counts[key].append(now)
    return None


def _audit_log(event: str, **kwargs: object) -> None:
    """Log an OAuth event for audit trail."""
    logger.info(
        "OAuth audit: event=%s %s",
        event,
        " ".join(f"{k}={v}" for k, v in kwargs.items()),
    )


def _validate_redirect_uri(client_id: str, redirect_uri: str) -> str | None:
    """Validate redirect_uri against the registered client's URIs.

    Returns an error message if invalid, else None.
    Per RFC 6749 §10.6: redirect URIs must be pre-registered.
    """
    if client_id not in _clients:
        return "Unknown client_id"

    registered_uris = _clients[client_id].get("redirect_uris", [])

    # If no URIs were registered during dynamic registration,
    # only allow localhost/loopback (native app clients).
    # External redirect_uris require pre-registration to prevent open redirects.
    if not registered_uris:
        parsed = urlparse(redirect_uri)
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            return (
                "Client has no pre-registered redirect_uris. "
                "Non-localhost URIs must be registered during client registration."
            )
        return None

    if redirect_uri not in registered_uris:
        # Also check origin match for localhost development
        parsed = urlparse(redirect_uri)
        registered_origins = {
            urlparse(u).scheme + "://" + urlparse(u).netloc for u in registered_uris
        }
        if parsed.scheme + "://" + parsed.netloc not in registered_origins:
            return (
                f"redirect_uri not registered for this client. "
                f"Registered: {registered_uris}"
            )

    return None


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


def register_client(body: dict, client_ip: str = "") -> tuple[int, dict]:
    """Register a new OAuth client dynamically.

    Returns (status_code, response_body).
    """
    rate_err = _check_rate_limit("register", client_ip)
    if rate_err:
        return 429, {"error": "too_many_requests", "error_description": rate_err}

    client_id = secrets.token_urlsafe(24)
    # Generate a client_secret and return it to the registrant (RFC 7591 §3.2.1).
    # The flow uses PKCE (token_endpoint_auth_method: "none"), so the secret is
    # never verified again — but we store a SHA-256 hash rather than plaintext
    # so a memory dump of the process cannot be used to impersonate a client.
    client_secret = secrets.token_urlsafe(32)
    client_secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()

    redirect_uris = body.get("redirect_uris", [])
    if not redirect_uris:
        redirect_uris = []

    client = {
        "client_id": client_id,
        # Hash stored; plaintext is returned once and then discarded
        "client_secret_hash": client_secret_hash,
        "client_name": body.get("client_name", "MCP Client"),
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "created_at": time.time(),
    }
    _clients[client_id] = client

    _audit_log(
        "client_registered",
        client_id=client_id,
        client_name=client["client_name"],
        redirect_uris=redirect_uris,
        ip=client_ip,
    )

    return 201, {
        "client_id": client_id,
        "client_secret": client_secret,  # returned once; not stored in plaintext
        "client_name": client["client_name"],
        "redirect_uris": redirect_uris,
        "grant_types": client["grant_types"],
        "response_types": client["response_types"],
        "token_endpoint_auth_method": client["token_endpoint_auth_method"],
    }


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------


def build_authorize_redirect(params: dict, client_ip: str = "") -> tuple[int, str]:
    """Build the redirect for the /authorize endpoint.

    Returns (status_code, redirect_url_or_error_body).
    """
    rate_err = _check_rate_limit("authorize", client_ip)
    if rate_err:
        return 429, json.dumps(
            {"error": "too_many_requests", "error_description": rate_err}
        )

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

    # Validate redirect_uri against registered client (RFC 6749 §10.6)
    uri_err = _validate_redirect_uri(client_id, redirect_uri)
    if uri_err:
        _audit_log(
            "authorize_rejected",
            reason="invalid_redirect_uri",
            client_id=client_id,
            redirect_uri=redirect_uri,
            ip=client_ip,
        )
        return 400, json.dumps(
            {
                "error": "invalid_request",
                "error_description": uri_err,
            }
        )

    # Store the pending authorization request with a unique ID.
    pending_id = secrets.token_urlsafe(24)
    _auth_codes[pending_id] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "state": state,
        "scope": scope,
        "user_id": None,
        "expires_at": time.time() + 600,  # 10 minutes
        "authenticated": False,
        "client_ip": client_ip,
    }

    _audit_log(
        "authorize_started",
        pending_id=pending_id,
        client_id=client_id,
        ip=client_ip,
    )

    # Redirect to the Evidence Lab login page.  The UI detects the
    # ``mcp_auth`` query parameter and shows the login/register modal.
    # After login it redirects the browser to /mcp/complete?pending=...
    # which finalises the OAuth handshake.
    login_url = f"{_APP_BASE_URL}?mcp_auth={pending_id}"
    return 302, login_url


def complete_authorize(pending_id: str, user_id: str) -> tuple[int, str]:
    """Finalise the OAuth flow after the user has logged in.

    Called by the ``/mcp/complete`` endpoint once the browser has a valid
    session cookie.  Generates the authorization code and redirects the
    browser back to the MCP client's ``redirect_uri``.

    Returns (status_code, redirect_or_error_body).
    """
    _clean_expired(_auth_codes)

    if pending_id not in _auth_codes:
        _audit_log(
            "authorize_complete_failed",
            reason="expired_or_invalid",
            pending_id=pending_id,
        )
        return 400, json.dumps(
            {
                "error": "invalid_request",
                "error_description": "Authorization request expired or invalid",
            }
        )

    pending = _auth_codes.pop(pending_id)

    # Generate the actual authorization code
    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        **pending,
        "user_id": user_id,
        "authenticated": True,
        "expires_at": time.time() + 300,  # 5 minutes to exchange
    }

    _audit_log(
        "authorize_completed",
        user_id=user_id,
        client_id=pending["client_id"],
    )

    # Redirect back to the MCP client
    redirect_uri = pending["redirect_uri"]
    callback_params = {"code": code}
    if pending.get("state"):
        callback_params["state"] = pending["state"]

    separator = "&" if "?" in redirect_uri else "?"
    redirect_url = f"{redirect_uri}{separator}{urlencode(callback_params)}"
    return 302, redirect_url


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


def exchange_token(body: dict, client_ip: str = "") -> tuple[int, dict]:
    """Exchange an authorization code for a Bearer token.

    Validates the PKCE code_verifier against the stored code_challenge.
    Returns (status_code, response_body).
    """
    rate_err = _check_rate_limit("token", client_ip)
    if rate_err:
        return 429, {"error": "too_many_requests", "error_description": rate_err}

    _clean_expired(_auth_codes)

    grant_type = body.get("grant_type", "")
    code = body.get("code", "")
    code_verifier = body.get("code_verifier", "")

    if grant_type != "authorization_code":
        return 400, {"error": "unsupported_grant_type"}

    if code not in _auth_codes:
        _audit_log("token_exchange_failed", reason="invalid_code", ip=client_ip)
        return 400, {
            "error": "invalid_grant",
            "error_description": "Invalid or expired code",
        }

    pending = _auth_codes.pop(code)

    if not pending.get("authenticated"):
        _audit_log(
            "token_exchange_failed",
            reason="not_authenticated",
            ip=client_ip,
        )
        return 400, {
            "error": "invalid_grant",
            "error_description": "Authorization not completed",
        }

    # Validate PKCE (required — reject if missing)
    if not code_verifier:
        _audit_log(
            "token_exchange_failed",
            reason="missing_code_verifier",
            ip=client_ip,
        )
        return 400, {
            "error": "invalid_grant",
            "error_description": "code_verifier is required (PKCE)",
        }

    expected = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected_b64 = base64.urlsafe_b64encode(expected).rstrip(b"=").decode("ascii")
    if expected_b64 != pending["code_challenge"]:
        _audit_log(
            "token_exchange_failed",
            reason="pkce_mismatch",
            user_id=pending.get("user_id"),
            ip=client_ip,
        )
        return 400, {
            "error": "invalid_grant",
            "error_description": "PKCE verification failed",
        }

    # Issue a JWT access token
    if not AUTH_SECRET:
        logger.error("AUTH_SECRET_KEY not configured — cannot issue tokens")
        return 500, {
            "error": "server_error",
            "error_description": "Token signing key not configured",
        }

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

    _audit_log(
        "token_issued",
        user_id=pending["user_id"],
        client_id=pending["client_id"],
        ip=client_ip,
    )

    return 200, {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": TOKEN_LIFETIME,
        "scope": pending.get("scope", ""),
    }
