"""Brief Central routes — briefs, their sharing and comments.

Briefs are user-owned. Sharing is viewer-only: a share row grants read access
to a single user (matched by email) or to every member of a group (matched by
group name); see services/brief_sharing.py. Templates and voice & tone
profiles live in routes/brief_library.py.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import Brief, BriefComment, BriefShare, User, UserGroup
from ui.backend.auth.schemas import (
    BriefCommentCreate,
    BriefCommentRead,
    BriefCommentUpdate,
    BriefCreate,
    BriefListItem,
    BriefRead,
    BriefShareCreate,
    BriefUpdate,
)
from ui.backend.auth.users import current_active_user
from ui.backend.services.brief_sharing import (
    add_share,
    owner_name,
    remove_share,
    share_targets,
    shared_with,
    user_group_ids,
)

logger = logging.getLogger(__name__)

# Share-dialog suggestions: enough characters to be a deliberate lookup, and a
# short list so the dialog never doubles as a directory dump.
MIN_SHARE_QUERY_CHARS = 2
SHARE_SUGGESTION_LIMIT = 8
router = APIRouter()

_BRIEF_NOT_FOUND = "Brief not found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_owned_brief(
    session: AsyncSession, brief_id: uuid.UUID, user: User
) -> Brief:
    """Load a brief owned by *user* or raise 404."""
    result = await session.execute(
        select(Brief).where(Brief.id == brief_id, Brief.user_id == user.id)
    )
    brief = result.scalars().first()
    if not brief:
        raise HTTPException(status_code=404, detail=_BRIEF_NOT_FOUND)
    return brief


async def _get_viewable_brief(
    session: AsyncSession, brief_id: uuid.UUID, user: User
) -> tuple[Brief, bool]:
    """Load a brief the user owns or was granted view access to.

    Returns (brief, can_edit). Raises 404 when the brief does not exist or the
    user has no access — the two cases are indistinguishable on purpose.
    """
    result = await session.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalars().first()
    if not brief:
        raise HTTPException(status_code=404, detail=_BRIEF_NOT_FOUND)
    if brief.user_id == user.id:
        return brief, True
    group_ids = await user_group_ids(session, user.id)
    share_rows = await session.execute(
        select(BriefShare.id).where(
            BriefShare.brief_id == brief_id,
            shared_with(BriefShare, user.id, group_ids),
        )
    )
    if not share_rows.scalars().first():
        raise HTTPException(status_code=404, detail=_BRIEF_NOT_FOUND)
    return brief, False


async def _to_brief_read(
    session: AsyncSession, brief: Brief, can_edit: bool
) -> BriefRead:
    """Build the full read model, including owner name and share targets."""
    owner = await session.get(User, brief.user_id)
    return BriefRead(
        id=brief.id,
        user_id=brief.user_id,
        title=brief.title,
        query=brief.query,
        data_source=brief.data_source,
        voice_profile_id=brief.voice_profile_id,
        content=brief.content,
        owner_name=owner_name(owner) if owner else None,
        can_edit=can_edit,
        shared_with=(
            await share_targets(session, BriefShare, BriefShare.brief_id, brief.id)
            if can_edit
            else []
        ),
        created_at=brief.created_at,
        updated_at=brief.updated_at,
    )


def _to_list_item(
    brief: Brief, owner_name: str | None, share_count: int
) -> BriefListItem:
    """Compact card model for list views."""
    content = brief.content or {}
    sections = content.get("sections") or []
    return BriefListItem(
        id=brief.id,
        title=brief.title,
        query=brief.query,
        data_source=brief.data_source,
        voice_profile_id=brief.voice_profile_id,
        section_count=len(sections),
        source_count=content.get("sourceCount") or 0,
        owner_name=owner_name,
        share_count=share_count,
        created_at=brief.created_at,
        updated_at=brief.updated_at,
    )


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------


@router.post("/briefs/", response_model=BriefRead, tags=["briefs"])
async def create_brief(
    body: BriefCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Save a new brief."""
    brief = Brief(
        user_id=user.id,
        title=body.title,
        query=body.query,
        data_source=body.data_source,
        voice_profile_id=body.voice_profile_id,
        content=body.content,
    )
    session.add(brief)
    await session.commit()
    await session.refresh(brief)
    return await _to_brief_read(session, brief, can_edit=True)


@router.get("/briefs/", tags=["briefs"])
async def list_briefs(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List the current user's briefs (compact, newest first)."""
    result = await session.execute(
        select(Brief).where(Brief.user_id == user.id).order_by(Brief.updated_at.desc())
    )
    briefs = result.scalars().all()
    counts = await session.execute(
        select(BriefShare.brief_id, func.count(BriefShare.id))
        .where(BriefShare.brief_id.in_([b.id for b in briefs]))
        .group_by(BriefShare.brief_id)
    )
    count_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in counts.all()}
    return [_to_list_item(b, None, count_map.get(b.id, 0)) for b in briefs]


@router.get("/briefs/shared", tags=["briefs"])
async def list_shared_briefs(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List briefs shared with the current user (directly or via a group)."""
    group_ids = await user_group_ids(session, user.id)
    result = await session.execute(
        select(Brief)
        .join(BriefShare, BriefShare.brief_id == Brief.id)
        .where(shared_with(BriefShare, user.id, group_ids), Brief.user_id != user.id)
        .order_by(Brief.updated_at.desc())
        .distinct()
    )
    items = []
    for brief in result.scalars().all():
        owner = await session.get(User, brief.user_id)
        items.append(_to_list_item(brief, owner_name(owner) if owner else None, 0))
    return items


@router.get("/briefs/share-targets", tags=["briefs"])
async def search_share_targets(
    q: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Suggest people and groups matching ``q`` for the share dialog.

    Matching is on email, first/last name and group name. Requires at least
    two characters and returns a short list, so the dialog helps someone who
    already knows who they are looking for rather than listing the directory.
    """
    term = (q or "").strip()
    if len(term) < MIN_SHARE_QUERY_CHARS:
        return {"users": [], "groups": []}
    like = f"%{term.lower()}%"

    user_rows = await session.execute(
        select(User)
        .where(
            User.id != user.id,
            or_(
                func.lower(User.email).like(like),
                func.lower(func.coalesce(User.first_name, "")).like(like),
                func.lower(func.coalesce(User.last_name, "")).like(like),
            ),
        )
        .order_by(User.email)
        .limit(SHARE_SUGGESTION_LIMIT)
    )
    group_rows = await session.execute(
        select(UserGroup)
        .where(func.lower(UserGroup.name).like(like))
        .order_by(UserGroup.name)
        .limit(SHARE_SUGGESTION_LIMIT)
    )
    return {
        "users": [
            {"email": u.email, "name": u.full_name or u.email}
            # unique(): User eager-loads collections (oauth accounts), which
            # SQLAlchemy requires be de-duplicated before iterating.
            for u in user_rows.scalars().unique().all()
        ],
        "groups": [{"name": g.name} for g in group_rows.scalars().all()],
    }


@router.get("/briefs/{brief_id}", response_model=BriefRead, tags=["briefs"])
async def get_brief(
    brief_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Load a single brief the user owns or can view."""
    brief, can_edit = await _get_viewable_brief(session, brief_id, user)
    return await _to_brief_read(session, brief, can_edit)


@router.put("/briefs/{brief_id}", response_model=BriefRead, tags=["briefs"])
async def update_brief(
    brief_id: uuid.UUID,
    body: BriefUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update a brief (owner only)."""
    brief = await _get_owned_brief(session, brief_id, user)
    if body.title is not None:
        brief.title = body.title
    if body.query is not None:
        brief.query = body.query
    if body.voice_profile_id is not None:
        brief.voice_profile_id = body.voice_profile_id
    if body.content is not None:
        brief.content = body.content
    await session.commit()
    await session.refresh(brief)
    return await _to_brief_read(session, brief, can_edit=True)


@router.delete("/briefs/{brief_id}", status_code=204, tags=["briefs"])
async def delete_brief(
    brief_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a brief (owner only)."""
    brief = await _get_owned_brief(session, brief_id, user)
    await session.delete(brief)
    await session.commit()


# ---------------------------------------------------------------------------
# Shares
# ---------------------------------------------------------------------------


@router.post("/briefs/{brief_id}/shares", response_model=BriefRead, tags=["briefs"])
async def add_brief_share(
    brief_id: uuid.UUID,
    body: BriefShareCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Grant viewer access to a user (by email) or group (by name)."""
    brief = await _get_owned_brief(session, brief_id, user)
    await add_share(
        session, BriefShare, BriefShare.brief_id, brief.id, user, body.target, "brief"
    )
    await session.refresh(brief)
    return await _to_brief_read(session, brief, can_edit=True)


@router.delete("/briefs/{brief_id}/shares/{share_id}", status_code=204, tags=["briefs"])
async def remove_brief_share(
    brief_id: uuid.UUID,
    share_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Revoke a share (owner only)."""
    brief = await _get_owned_brief(session, brief_id, user)
    await remove_share(session, BriefShare, BriefShare.brief_id, brief.id, share_id)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

_COMMENT_NOT_FOUND = "Comment not found"


def _comment_author_name(author: User | None) -> str:
    """Display name for a comment's author, falling back to their email."""
    if not author:
        return "Unknown"
    full = " ".join(p for p in [author.first_name, author.last_name] if p).strip()
    return full or author.email


async def _to_comment_read(
    session: AsyncSession, comment: BriefComment, user: User
) -> BriefCommentRead:
    """Serialise a comment, resolving its author for display."""
    author = await session.get(User, comment.user_id)
    return BriefCommentRead(
        id=comment.id,
        brief_id=comment.brief_id,
        parent_id=comment.parent_id,
        section_id=comment.section_id,
        quote=comment.quote,
        quote_prefix=comment.quote_prefix,
        quote_suffix=comment.quote_suffix,
        body=comment.body,
        resolved=comment.resolved,
        author_name=_comment_author_name(author),
        author_email=author.email if author else "",
        is_mine=comment.user_id == user.id,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


@router.get(
    "/briefs/{brief_id}/comments",
    response_model=list[BriefCommentRead],
    tags=["brief-comments"],
)
async def list_brief_comments(
    brief_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Every comment on a brief, oldest first, for anyone who can view it."""
    await _get_viewable_brief(session, brief_id, user)
    result = await session.execute(
        select(BriefComment)
        .where(BriefComment.brief_id == brief_id)
        .order_by(BriefComment.created_at)
    )
    return [await _to_comment_read(session, c, user) for c in result.scalars().all()]


@router.post(
    "/briefs/{brief_id}/comments",
    response_model=BriefCommentRead,
    status_code=201,
    tags=["brief-comments"],
)
async def create_brief_comment(
    brief_id: uuid.UUID,
    body: BriefCommentCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Add a comment, or a reply when ``parent_id`` is given.

    Anyone who can view the brief can comment — that is the point of sharing a
    brief for review.
    """
    await _get_viewable_brief(session, brief_id, user)
    if body.parent_id:
        parent = await session.get(BriefComment, body.parent_id)
        # A reply must belong to the same brief, and threads stay one deep so
        # the rail never becomes a tree.
        if not parent or parent.brief_id != brief_id or parent.parent_id:
            raise HTTPException(status_code=404, detail=_COMMENT_NOT_FOUND)
    comment = BriefComment(
        brief_id=brief_id,
        user_id=user.id,
        parent_id=body.parent_id,
        section_id=body.section_id,
        quote=body.quote,
        quote_prefix=body.quote_prefix,
        quote_suffix=body.quote_suffix,
        body=body.body,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return await _to_comment_read(session, comment, user)


@router.patch(
    "/briefs/{brief_id}/comments/{comment_id}",
    response_model=BriefCommentRead,
    tags=["brief-comments"],
)
async def update_brief_comment(
    brief_id: uuid.UUID,
    comment_id: uuid.UUID,
    body: BriefCommentUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Edit a comment's text (author only) or resolve it (author or brief owner)."""
    brief, is_owner = await _get_viewable_brief(session, brief_id, user)
    comment = await session.get(BriefComment, comment_id)
    if not comment or comment.brief_id != brief_id:
        raise HTTPException(status_code=404, detail=_COMMENT_NOT_FOUND)
    if body.body is not None:
        # Only the person who wrote it may change what it says.
        if comment.user_id != user.id:
            raise HTTPException(status_code=403, detail="Not your comment")
        comment.body = body.body
    if body.resolved is not None:
        # Resolving is a review action: the thread's author or the brief owner.
        if comment.user_id != user.id and not is_owner:
            raise HTTPException(status_code=403, detail="Cannot resolve this comment")
        comment.resolved = body.resolved
        comment.resolved_by_id = user.id if body.resolved else None
        comment.resolved_at = datetime.now(timezone.utc) if body.resolved else None
    await session.commit()
    await session.refresh(comment)
    return await _to_comment_read(session, comment, user)


@router.delete(
    "/briefs/{brief_id}/comments/{comment_id}",
    status_code=204,
    tags=["brief-comments"],
)
async def delete_brief_comment(
    brief_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a comment (its author, or the brief owner clearing a thread)."""
    brief, is_owner = await _get_viewable_brief(session, brief_id, user)
    comment = await session.get(BriefComment, comment_id)
    if not comment or comment.brief_id != brief_id:
        raise HTTPException(status_code=404, detail=_COMMENT_NOT_FOUND)
    if comment.user_id != user.id and not is_owner:
        raise HTTPException(status_code=403, detail="Not your comment")
    await session.delete(comment)
    await session.commit()
