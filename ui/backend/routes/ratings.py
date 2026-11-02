"""Ratings routes — create, read, delete user ratings; admin list & export."""

import io
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from pipeline.db import get_application_config
from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User, UserActivity, UserRating
from ui.backend.auth.schemas import (
    VALID_RATING_TYPES,
    VALID_RESPONSE_STATUSES,
    RatingCreate,
    RatingRead,
    RatingResponseUpdate,
)
from ui.backend.auth.users import current_superuser, optional_current_user
from ui.backend.utils.app_limits import get_rate_limit_ratings, limiter

logger = logging.getLogger(__name__)

router = APIRouter()

RATE_LIMIT_RATINGS = get_rate_limit_ratings()

# httpOnly cookie holding the random ID of an anonymous rater's browser, so the
# browser keeps one rating per item. JavaScript cannot read it.
RATER_COOKIE_NAME = "evidencelab_rater"
RATER_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() != "false"

# The feedback button is open to every visitor and each report is kept as its
# own row, so page feedback is not owned by a browser.
PAGE_FEEDBACK_TYPE = "page_feedback"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rating_to_read(
    rating: UserRating,
    user: User | None = None,
    responder: User | None = None,
) -> RatingRead:
    """Convert a UserRating ORM object to a RatingRead response.

    ``user`` is the rating creator; ``responder`` is the admin who last
    edited ``response_status`` / ``response_notes`` (may be ``None`` if
    no response has been recorded or the responder was deleted).
    """
    return RatingRead(
        id=rating.id,
        user_id=rating.user_id,
        user_email=user.email if user else None,
        user_display_name=user.full_name if user else None,
        rating_type=rating.rating_type,
        reference_id=rating.reference_id,
        item_id=rating.item_id,
        score=rating.score,
        comment=rating.comment,
        context=rating.context,
        url=rating.url,
        response_status=rating.response_status,
        response_notes=rating.response_notes,
        responded_by_user_id=rating.responded_by_user_id,
        responded_by_email=responder.email if responder else None,
        responded_by_display_name=responder.full_name if responder else None,
        responded_at=rating.responded_at,
        created_at=rating.created_at,
        updated_at=rating.updated_at,
    )


def anonymous_ratings_enabled() -> bool:
    """Whether visitors who are not signed in may rate (config.json)."""
    features = get_application_config().get("features", {})
    return features.get("anonymous_ratings") is True


def _read_anonymous_id(request: Request) -> uuid.UUID | None:
    """Return the rater cookie's browser ID, or None if absent or malformed."""
    raw = request.cookies.get(RATER_COOKIE_NAME)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def _set_rater_cookie(response: Response, anonymous_id: uuid.UUID) -> None:
    response.set_cookie(
        RATER_COOKIE_NAME,
        str(anonymous_id),
        max_age=RATER_COOKIE_MAX_AGE,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@dataclass(frozen=True)
class _Rater:
    """Who owns a rating: a signed-in user or an anonymous browser.

    Both IDs are None only for anonymous page feedback, which has no owner.
    """

    user: User | None = None
    anonymous_id: uuid.UUID | None = None
    new_cookie: bool = False

    @property
    def has_owner(self) -> bool:
        return self.user is not None or self.anonymous_id is not None

    def owns(self):
        """SQL condition selecting this rater's ratings."""
        if self.user is not None:
            return UserRating.user_id == self.user.id
        return UserRating.anonymous_id == self.anonymous_id


def _rater_for_write(request: Request, user: User | None, rating_type: str) -> _Rater:
    """Resolve who is submitting a rating, refusing anonymous ratings if off."""
    if user is not None:
        return _Rater(user=user)
    if rating_type == PAGE_FEEDBACK_TYPE:
        return _Rater()
    if not anonymous_ratings_enabled():
        raise HTTPException(status_code=401, detail="Sign in to rate")
    anonymous_id = _read_anonymous_id(request)
    if anonymous_id is not None:
        return _Rater(anonymous_id=anonymous_id)
    return _Rater(anonymous_id=uuid.uuid4(), new_cookie=True)


def _rater_for_read(request: Request, user: User | None) -> _Rater | None:
    """Resolve whose ratings to return or delete; None if the caller has none."""
    if user is not None:
        return _Rater(user=user)
    if not anonymous_ratings_enabled():
        return None
    anonymous_id = _read_anonymous_id(request)
    return _Rater(anonymous_id=anonymous_id) if anonymous_id else None


async def _find_own_rating(
    session: AsyncSession, rater: _Rater, body: RatingCreate
) -> UserRating | None:
    """The rater's existing rating of the same item, if any."""
    if not rater.has_owner:
        return None
    stmt = select(UserRating).where(
        rater.owns(),
        UserRating.rating_type == body.rating_type,
        UserRating.reference_id == body.reference_id,
        func.coalesce(UserRating.item_id, "") == (body.item_id or ""),
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def _mark_search_rated(
    session: AsyncSession, user_id: uuid.UUID, body: RatingCreate
) -> None:
    """Flag the signed-in user's search activity record as rated."""
    try:
        ref_uuid = uuid.UUID(body.reference_id)
        await session.execute(
            update(UserActivity)
            .where(
                UserActivity.user_id == user_id,
                UserActivity.search_id == ref_uuid,
            )
            .values(has_ratings=True)
        )
        await session.commit()
    except (ValueError, Exception):
        logger.debug("Could not mark activity has_ratings (non-critical)")


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=RatingRead, tags=["ratings"])
@limiter.limit(RATE_LIMIT_RATINGS)
async def upsert_rating(
    request: Request,
    response: Response,
    body: RatingCreate,
    user: User | None = Depends(optional_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create or update a rating (upsert on owner + type + reference + item).

    The owner is the signed-in user or, when ``features.anonymous_ratings`` is
    on, the anonymous browser identified by the rater cookie, which is issued
    on the first rating. Anonymous ratings are refused with 401 when the
    feature is off. Page feedback is open to everyone and always stored as a
    new row.
    """
    rater = _rater_for_write(request, user, body.rating_type)
    existing = await _find_own_rating(session, rater, body)

    if existing:
        existing.score = body.score
        existing.comment = body.comment
        existing.context = body.context
        existing.url = body.url
        existing.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(existing)
        rating = existing
    else:
        rating = UserRating(
            user_id=user.id if user else None,
            anonymous_id=rater.anonymous_id,
            rating_type=body.rating_type,
            reference_id=body.reference_id,
            item_id=body.item_id,
            score=body.score,
            comment=body.comment,
            context=body.context,
            url=body.url,
        )
        session.add(rating)
        await session.commit()
        await session.refresh(rating)

    if rater.new_cookie and rater.anonymous_id is not None:
        _set_rater_cookie(response, rater.anonymous_id)

    if user and body.rating_type in ("search_result", "ai_summary"):
        await _mark_search_rated(session, user.id, body)

    return _rating_to_read(rating, user)


@router.get("/mine", response_model=list[RatingRead], tags=["ratings"])
async def get_my_ratings(
    request: Request,
    rating_type: Optional[str] = Query(None),
    reference_id: Optional[str] = Query(None),
    user: User | None = Depends(optional_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Retrieve the caller's own ratings, optionally filtered.

    An anonymous browser gets the ratings made under its rater cookie when
    ``features.anonymous_ratings`` is on, and an empty list otherwise.
    """
    rater = _rater_for_read(request, user)
    if rater is None:
        return []
    stmt = select(UserRating).where(rater.owns())
    if rating_type:
        stmt = stmt.where(UserRating.rating_type == rating_type)
    if reference_id:
        stmt = stmt.where(UserRating.reference_id == reference_id)
    stmt = stmt.order_by(UserRating.updated_at.desc())
    result = await session.execute(stmt)
    ratings = result.scalars().all()
    return [_rating_to_read(r, user) for r in ratings]


@router.delete("/{rating_id}", status_code=204, tags=["ratings"])
async def delete_my_rating(
    request: Request,
    rating_id: uuid.UUID,
    user: User | None = Depends(optional_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete one of the caller's own ratings (signed-in user or rater cookie)."""
    rater = _rater_for_read(request, user)
    if rater is None:
        raise HTTPException(status_code=401, detail="Sign in to rate")
    result = await session.execute(
        select(UserRating).where(UserRating.id == rating_id, rater.owns())
    )
    rating = result.scalars().first()
    if rating is None:
        raise HTTPException(status_code=404, detail="Rating not found")
    await session.delete(rating)
    await session.commit()


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/all", tags=["ratings"])
async def list_all_ratings(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    user_email: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    rating_type: Optional[str] = Query(None),
    response_status: Optional[str] = Query(None),
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """List all ratings with pagination (superuser only).

    Joins ``users`` twice: once for the rating creator and once
    (aliased as ``Responder``) for the admin who last recorded a
    response. Both joins are LEFT OUTER so ratings with no responder
    (or an anonymous creator) are still returned.
    """
    Responder = aliased(User)
    base = (
        select(UserRating, User, Responder)
        .outerjoin(User, UserRating.user_id == User.id)  # type: ignore[arg-type]
        .outerjoin(
            Responder,
            UserRating.responded_by_user_id == Responder.id,  # type: ignore[arg-type]
        )
    )

    if rating_type and rating_type in VALID_RATING_TYPES:
        base = base.where(UserRating.rating_type == rating_type)  # type: ignore[arg-type]

    if user_email:
        base = base.where(User.email == user_email)  # type: ignore[arg-type]

    if response_status and response_status in VALID_RESPONSE_STATUSES:
        base = base.where(UserRating.response_status == response_status)  # type: ignore[arg-type]

    if search:
        pattern = f"%{search}%"
        base = base.where(  # type: ignore[arg-type]
            User.email.ilike(pattern)  # type: ignore[attr-defined]
            | UserRating.reference_id.ilike(pattern)  # type: ignore[attr-defined]
            | UserRating.comment.ilike(pattern)  # type: ignore[attr-defined]
            | UserRating.response_notes.ilike(pattern)  # type: ignore[attr-defined]
        )

    # Count total
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    # Sorting
    sort_col_map = {
        "created_at": UserRating.created_at,
        "updated_at": UserRating.updated_at,
        "score": UserRating.score,
        "rating_type": UserRating.rating_type,
        "user_email": User.email,
        "response_status": UserRating.response_status,
        "responded_at": UserRating.responded_at,
    }
    sort_col = sort_col_map.get(sort_by, UserRating.created_at)
    if order == "asc":
        base = base.order_by(sort_col.asc())  # type: ignore[attr-defined]
    else:
        base = base.order_by(sort_col.desc())  # type: ignore[attr-defined]

    # Pagination
    offset = (page - 1) * page_size
    base = base.offset(offset).limit(page_size)

    result = await session.execute(base)
    rows = result.unique().all()
    items = [
        _rating_to_read(rating, user, responder) for rating, user, responder in rows
    ]

    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/export", tags=["ratings"])
async def export_ratings(
    rating_type: Optional[str] = Query(None),
    response_status: Optional[str] = Query(None),
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Export all ratings as XLSX (superuser only).

    Includes the admin-response columns (status, notes, responder
    email, responded_at) so the export reflects exactly what is
    visible in the admin grid.
    """
    import openpyxl

    Responder = aliased(User)
    stmt = (
        select(UserRating, User, Responder)
        .outerjoin(User, UserRating.user_id == User.id)
        .outerjoin(
            Responder,
            UserRating.responded_by_user_id == Responder.id,  # type: ignore[arg-type]
        )
    )
    if rating_type and rating_type in VALID_RATING_TYPES:
        stmt = stmt.where(UserRating.rating_type == rating_type)
    if response_status and response_status in VALID_RESPONSE_STATUSES:
        stmt = stmt.where(UserRating.response_status == response_status)  # type: ignore[arg-type]
    stmt = stmt.order_by(UserRating.created_at.desc())

    result = await session.execute(stmt)
    rows = result.unique().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Ratings"
    headers = [
        "Date",
        "User Email",
        "User Name",
        "Type",
        "Score",
        "Reference ID",
        "Item ID",
        "Comment",
        "URL",
        "Response Status",
        "Response Notes",
        "Responded By",
        "Responded At",
    ]
    ws.append(headers)

    for rating, user, responder in rows:
        ws.append(
            [
                (
                    rating.created_at.strftime("%Y-%m-%d %H:%M")
                    if rating.created_at
                    else ""
                ),
                user.email if user else "",
                user.full_name if user else "",
                rating.rating_type,
                rating.score,
                rating.reference_id,
                rating.item_id or "",
                rating.comment or "",
                rating.url or "",
                rating.response_status or "",
                rating.response_notes or "",
                responder.email if responder else "",
                (
                    rating.responded_at.strftime("%Y-%m-%d %H:%M")
                    if rating.responded_at
                    else ""
                ),
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = (
        f"ratings_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/{rating_id}/response", response_model=RatingRead, tags=["ratings"])
async def update_rating_response(
    rating_id: uuid.UUID,
    body: RatingResponseUpdate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Record or clear an admin response on a rating (superuser only).

    Both fields are optional; passing both as ``None`` clears the
    response (status, notes, and audit fields are all set to ``NULL``).
    Otherwise ``responded_by_user_id`` and ``responded_at`` are
    refreshed to the current admin / timestamp on every edit.
    """
    result = await session.execute(select(UserRating).where(UserRating.id == rating_id))
    rating = result.scalars().first()
    if rating is None:
        raise HTTPException(status_code=404, detail="Rating not found")

    is_clear = body.response_status is None and not body.response_notes
    if is_clear:
        rating.response_status = None
        rating.response_notes = None
        rating.responded_by_user_id = None
        rating.responded_at = None
    else:
        rating.response_status = body.response_status
        rating.response_notes = body.response_notes
        rating.responded_by_user_id = admin.id
        rating.responded_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(rating)

    # Re-fetch the rating creator (and resolved responder) so the
    # response payload carries display names just like /ratings/all.
    creator = None
    if rating.user_id:
        creator_row = await session.execute(
            select(User).where(User.id == rating.user_id)
        )
        creator = creator_row.scalars().first()

    responder = None
    if rating.responded_by_user_id:
        responder_row = await session.execute(
            select(User).where(User.id == rating.responded_by_user_id)
        )
        responder = responder_row.scalars().first()

    logger.info(
        "Admin %s updated response on rating %s (status=%s)",
        admin.email,
        rating.id,
        rating.response_status,
    )
    return _rating_to_read(rating, creator, responder)
