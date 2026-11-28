"""Apply the data-source policy to authenticated MCP requests."""

from uuid import UUID

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from mcp_server.audit import request_auth


class MCPSourceDenied(PermissionError):
    """The current user may not access the requested data source."""


def source_keys(data_source: str | None) -> tuple[str, str]:
    """Return the configured dataset key and storage name."""
    from pipeline.db import load_datasources_config, resolve_data_source

    source = resolve_data_source(data_source)
    datasets = load_datasources_config()["datasources"]
    if source in datasets:
        return source, datasets[source].get("data_subdir") or source
    for key, config in datasets.items():
        if config.get("data_subdir") == source:
            return key, source
    raise ValueError("Invalid data source. Choose a configured data source.")


async def resolve_mcp_source(data_source: str | None) -> str:
    """Require a configured source and apply the web group policy to JWT users."""
    _, source = await run_in_threadpool(source_keys, data_source)
    principal = request_auth.get()
    if principal.get("type") == "jwt":
        await check_group_access(source, principal.get("user_id"))
    return source


async def check_group_access(source: str, user_id: str | None) -> None:
    from ui.backend.auth.optional_user import USER_MODULE_ENABLED

    if not USER_MODULE_ENABLED:
        return

    from ui.backend.auth.db import async_session_factory
    from ui.backend.auth.models import User
    from ui.backend.services.permissions import ensure_data_source_access

    try:
        uuid = UUID(user_id or "")
    except ValueError:
        raise MCPSourceDenied(
            "Sign in to Evidence Lab again to use this tool."
        ) from None

    async with async_session_factory() as session:
        user = await session.get(User, uuid)
        if user is None or not user.is_active:
            raise MCPSourceDenied("Sign in to Evidence Lab again to use this tool.")
        try:
            await ensure_data_source_access(session, user, source)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            raise MCPSourceDenied(
                "You don't have access to this data source. Ask an administrator."
            ) from None
