"""Shared optional-user dependency for routes that work with or without auth.

Several routes resolve the current user opportunistically — authenticated
users get attributed, anonymous visitors still work. Historically each route
file carried its own copy of the ``USER_MODULE`` conditional-import block;
new routes should import :data:`resolve_optional_user` from here instead of
adding another copy.
"""

import os
from typing import Any, Callable

_UM_RAW = os.environ.get("USER_MODULE", "off").lower()
USER_MODULE_ENABLED = _UM_RAW not in ("off", "0", "false", "no")


async def _anonymous_user() -> None:
    """No-op user resolver for deployments without the user module."""
    return None


def _build_dep() -> Callable[..., Any]:
    """Resolve the dependency once at import (same timing as the old blocks)."""
    if USER_MODULE_ENABLED:
        from ui.backend.auth.users import optional_current_user

        return optional_current_user
    return _anonymous_user


# FastAPI dependency: yields the authenticated user or None.
resolve_optional_user = _build_dep()
