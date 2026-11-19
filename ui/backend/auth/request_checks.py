"""Checks shared by the API-key dependency and the sign-in middleware.

Both gates decide whether a request may skip authentication (an exempt path)
and whether it carries a real session. Keeping one implementation stops the
two drifting apart: the API-key check once accepted any non-empty session
cookie, and both matched exempt paths as raw string prefixes, so ``/docs``
also exempted ``/docsearch``.
"""

import jwt

JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = ["fastapi-users:auth"]


def path_is_under(path: str, prefix: str) -> bool:
    """True if *path* is *prefix* itself or a path beneath it.

    Matching is by whole path segment: ``/docs`` covers ``/docs`` and
    ``/docs/oauth2-redirect`` but not ``/docsearch``.
    """
    base = prefix.rstrip("/")
    return path == base or path.startswith(base + "/")


def is_exempt_path(path: str, prefixes: tuple[str, ...]) -> bool:
    """True if *path* falls under any of *prefixes* (see :func:`path_is_under`)."""
    return any(path_is_under(path, prefix) for prefix in prefixes)


def is_valid_session_token(token: str, secret: str) -> bool:
    """True if *token* is a session JWT signed with *secret* and not expired."""
    if not token or not secret:
        return False
    try:
        jwt.decode(token, secret, algorithms=[JWT_ALGORITHM], audience=JWT_AUDIENCE)
    except jwt.PyJWTError:
        return False
    return True
