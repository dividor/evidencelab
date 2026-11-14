"""Brief versions routes: the whole-brief version Log, one version compared
with the one before it, and restoring a brief to a version.

Every signed-in user who can open a brief can read its versions; only its
owner can restore one. Versions are written by the save path itself
(``brief_central.store_brief_content``), never by these routes' callers.
"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User
from ui.backend.auth.schemas import BriefRead, BriefVersionItem, BriefVersionRead
from ui.backend.auth.users import current_active_user
from ui.backend.routes.brief_central import (
    _get_owned_brief,
    _get_viewable_brief,
    _to_brief_read,
    citation_http_error,
    store_brief_content,
)
from ui.backend.services import brief_citations as bc
from ui.backend.services import brief_version_store as store
from ui.backend.services.brief_versions import KIND_BRIEF_RESTORE
from ui.backend.utils.app_limits import get_rate_limits, limiter

router = APIRouter()
_RL_SEARCH, _RL_DEFAULT, _RL_AI = get_rate_limits()


@router.get(
    "/briefs/{brief_id}/versions",
    response_model=list[BriefVersionItem],
    tags=["brief-versions"],
)
@limiter.limit(_RL_DEFAULT)
async def list_brief_versions(
    request: Request,
    brief_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Every version of the brief, newest first."""
    await _get_viewable_brief(session, brief_id, user)
    return await store.list_versions(session, brief_id)


@router.get(
    "/briefs/{brief_id}/versions/{number}",
    response_model=BriefVersionRead,
    tags=["brief-versions"],
)
@limiter.limit(_RL_DEFAULT)
async def get_brief_version(
    request: Request,
    brief_id: uuid.UUID,
    number: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """One version, compared section by section with the version before it."""
    brief, can_edit = await _get_viewable_brief(session, brief_id, user)
    try:
        detail = await store.version_detail(session, brief, number)
    except bc.BriefCitationError as exc:
        raise citation_http_error(exc)
    return {**detail, "can_restore": can_edit and not detail["is_current"]}


@router.post(
    "/briefs/{brief_id}/versions/{number}/restore",
    response_model=BriefRead,
    tags=["brief-versions"],
)
@limiter.limit(_RL_DEFAULT)
async def restore_brief_version(
    request: Request,
    brief_id: uuid.UUID,
    number: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Restore the whole brief to a version (owner only). The restore is
    itself a new version, so it can be undone the same way."""
    brief = await _get_owned_brief(session, brief_id, user)
    try:
        content = await store.restored_content(session, brief, number)
    except bc.BriefCitationError as exc:
        raise citation_http_error(exc)
    if content.get("title"):
        brief.title = content["title"]
    await store_brief_content(
        session,
        brief,
        content,
        user,
        store.VersionChange(kind=KIND_BRIEF_RESTORE, detail=str(number)),
    )
    return await _to_brief_read(session, brief, can_edit=True)
