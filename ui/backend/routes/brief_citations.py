"""Brief citation routes: record a section's research run, reject it, change
the References grouping, store highlights, and read an original or a trace.

Every operation runs through ``services/brief_citations`` and saves the
recomputed brief, so the stored renumbered version, the screen, the Word
export, the Activity row and the citation check always agree. ``router``
needs Brief Central (the user module); ``anonymous_router`` serves the same
operations statelessly for briefs the browser keeps in localStorage.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User
from ui.backend.auth.optional_user import USER_MODULE_ENABLED, resolve_optional_user
from ui.backend.auth.schemas import (
    BriefCitationsOp,
    BriefGroupingUpdate,
    BriefHighlightsUpdate,
    BriefRead,
    BriefRunCreate,
)
from ui.backend.auth.users import current_active_user
from ui.backend.routes.brief_central import (
    _get_owned_brief,
    _get_viewable_brief,
    _to_brief_read,
    citation_http_error,
    store_brief_content,
)
from ui.backend.services import brief_citations as bc
from ui.backend.services.brief_activity import upsert_brief_activity
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.utils.app_limits import get_rate_limits, limiter

logger = logging.getLogger(__name__)

router = APIRouter()
anonymous_router = APIRouter()
_RL_SEARCH, _RL_DEFAULT, _RL_AI = get_rate_limits()


async def _apply_and_save(session: AsyncSession, brief, apply) -> BriefRead:
    """Run ``apply(content)`` on a copy of the stored content, save, respond."""
    try:
        content = apply(bc_copy(brief.content))
    except bc.BriefCitationError as exc:
        raise citation_http_error(exc)
    await store_brief_content(session, brief, content)
    return await _to_brief_read(session, brief, can_edit=True)


def bc_copy(content: dict) -> dict:
    import copy

    return copy.deepcopy(content or {})


@router.post(
    "/briefs/{brief_id}/sections/{section_id}/runs",
    response_model=BriefRead,
    tags=["brief-citations"],
)
async def record_section_run(
    brief_id: uuid.UUID,
    section_id: str,
    body: BriefRunCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Store the agent's original output for a section, map its sources into
    the brief, renumber the whole brief and return it."""
    brief = await _get_owned_brief(session, brief_id, user)
    return await _apply_and_save(
        session, brief, lambda c: bc.record_run(c, section_id, body.to_run())
    )


@router.post(
    "/briefs/{brief_id}/sections/{section_id}/runs/{run_id}/reject",
    response_model=BriefRead,
    tags=["brief-citations"],
)
async def reject_section_run(
    brief_id: uuid.UUID,
    section_id: str,
    run_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Reject edits: the run before the current one becomes current again."""
    brief = await _get_owned_brief(session, brief_id, user)
    return await _apply_and_save(
        session, brief, lambda c: bc.reject_run(c, section_id, run_id)
    )


@router.put(
    "/briefs/{brief_id}/reference-grouping",
    response_model=BriefRead,
    tags=["brief-citations"],
)
async def set_reference_grouping(
    brief_id: uuid.UUID,
    body: BriefGroupingUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Change how citations are numbered and the References list laid out."""
    brief = await _get_owned_brief(session, brief_id, user)
    return await _apply_and_save(
        session, brief, lambda c: bc.set_grouping(c, body.grouping)
    )


@router.put(
    "/briefs/{brief_id}/highlights",
    response_model=BriefRead,
    tags=["brief-citations"],
)
async def set_source_highlights(
    brief_id: uuid.UUID,
    body: BriefHighlightsUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Store the highlighter's claim matches on brief-wide sources."""
    brief = await _get_owned_brief(session, brief_id, user)
    return await _apply_and_save(
        session, brief, lambda c: bc.set_highlights(c, body.highlights)
    )


@router.get(
    "/briefs/{brief_id}/sections/{section_id}/runs/{run_id}",
    tags=["brief-citations"],
)
async def get_section_run(
    brief_id: uuid.UUID,
    section_id: str,
    run_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """One stored original: the agent's text and sources, its mapping to the
    brief's source ids and its agent -> display number table."""
    brief, _ = await _get_viewable_brief(session, brief_id, user)
    try:
        return bc.run_detail(brief.content or {}, section_id, run_id)
    except bc.BriefCitationError as exc:
        raise citation_http_error(exc)


@router.get(
    "/briefs/{brief_id}/sections/{section_id}/trace/{n}",
    tags=["brief-citations"],
)
async def trace_citation(
    brief_id: uuid.UUID,
    section_id: str,
    n: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Where a displayed ``[n]`` in a section came from."""
    brief, _ = await _get_viewable_brief(session, brief_id, user)
    try:
        return bc.trace(brief.content or {}, section_id, n)
    except bc.BriefCitationError as exc:
        raise citation_http_error(exc)


# ---------------------------------------------------------------------------
# Anonymous briefs (kept in the browser)
# ---------------------------------------------------------------------------


@anonymous_router.post("/brief/citations", tags=["brief"])
@limiter.limit(_RL_DEFAULT)
async def apply_citation_op(
    request: Request,
    body: BriefCitationsOp,
    user=Depends(resolve_optional_user),
):
    """Apply one citation operation to a brief the browser holds and return
    the stored form (for localStorage) and the read model (for display).
    Same semantics as the Brief Central endpoints; the Activity row is
    written by anonymous session when the user module is on. Two extra
    operations serve the browser-held brief: ``convert`` (an explicit
    conversion of a brief saved before citation format 2) and ``run_detail``
    (one stored original, returned as ``detail`` without any change)."""
    kind = body.op.get("type")
    try:
        if kind == "run_detail":
            return {
                "detail": bc.run_detail(
                    body.content, body.op["sectionId"], body.op["runId"]
                )
            }
        if kind == "convert":
            content = convert_legacy(bc_copy(body.content))[0]
        else:
            content = bc.apply_op(bc_copy(body.content), body.op)
        read = bc.expand_for_read(content)
    except bc.BriefCitationError as exc:
        raise citation_http_error(exc)
    except (KeyError, ValueError) as exc:
        raise citation_http_error(bc.BriefCitationError(f"Invalid operation: {exc}"))
    if USER_MODULE_ENABLED and kind != "read":
        await _log_anonymous_activity(content, user, body.session_id)
    return {"content": content, "read": read}


async def _log_anonymous_activity(content: dict, user, session_id) -> None:
    from ui.backend.auth.db import async_session_factory

    try:
        async with async_session_factory() as session:
            await upsert_brief_activity(
                session,
                content=content,
                title=content.get("title") or "",
                brief_id=None,
                user_id=getattr(user, "id", None),
                session_id=session_id,
            )
            await session.commit()
    except Exception:
        logger.warning("Brief activity row not written (anonymous)", exc_info=True)
