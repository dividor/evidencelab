"""Settling which data source a request works on, and whether the user may."""

from typing import Any

from starlette.concurrency import run_in_threadpool

from ui.backend.auth.optional_user import USER_MODULE_ENABLED
from ui.backend.utils.app_state import validate_data_source


async def settle_data_source(data_source: Any, user: Any, session: Any) -> str:
    """The request's data source, checked against config.json and the user's
    groups. Raises ValueError (400) if invalid, HTTPException (403) if refused.
    """
    source = await run_in_threadpool(validate_data_source, data_source)
    if USER_MODULE_ENABLED:
        from ui.backend.services.permissions import ensure_data_source_access

        await ensure_data_source_access(session, user, source)
    return source
