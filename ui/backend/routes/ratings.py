"""Ratings routes — create, read, delete user ratings; admin list & export."""

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User, UserActivity, UserRating
from ui.backend.auth.schemas import VALID_RATING_TYPES, RatingCreate, RatingRead
from ui.backend.auth.users import current_active_user, current_superuser

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rating_to_read(rating: UserRating, user: User | None = None) -> RatingRead:
    """Convert a UserRating ORM object to a RatingRead response."""
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
        created_at=rating.created_at,
        updated_at=rating.updated_at,
    )


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=RatingRead, tags=["ratings"])
async def upsert_rating(
    body: RatingCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create or update a rating (upsert on user + type + reference + item).

    If a rating already exists for the same user/type/reference_id/item_id
    combination, it is updated in place.
    """
    item_id_coalesce = body.item_id or ""

    # Check for existing rating
    stmt = select(UserRating).where(
        UserRating.user_id == user.id,
        UserRating.rating_type == body.rating_type,
        UserRating.reference_id == body.reference_id,
        func.coalesce(UserRating.item_id, "") == item_id_coalesce,
    )
    result = await session.execute(stmt)
    existing = result.scalars().first()

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
            user_id=user.id,
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

    # If this is a search-related rating, mark the activity record
    if body.rating_type in ("search_result", "ai_summary"):
        try:
            ref_uuid = uuid.UUID(body.reference_id)
            await session.execute(
                update(UserActivity)
                .where(
                    UserActivity.user_id == user.id,
                    UserActivity.search_id == ref_uuid,
                )
                .values(has_ratings=True)
            )
            await session.commit()
        except (ValueError, Exception):
            logger.debug("Could not mark activity has_ratings (non-critical)")

    return _rating_to_read(rating, user)


@router.get("/mine", response_model=list[RatingRead], tags=["ratings"])
async def get_my_ratings(
    rating_type: Optional[str] = Query(None),
    reference_id: Optional[str] = Query(None),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Retrieve the current user's own ratings, optionally filtered."""
    stmt = select(UserRating).where(UserRating.user_id == user.id)
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
    rating_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete one of the current user's ratings."""
    result = await session.execute(
        select(UserRating).where(
            UserRating.id == rating_id,
            UserRating.user_id == user.id,
        )
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
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """List all ratings with pagination (superuser only)."""
    base = select(UserRating, User).outerjoin(User, UserRating.user_id == User.id)

    if rating_type and rating_type in VALID_RATING_TYPES:
        base = base.where(UserRating.rating_type == rating_type)

    if user_email:
        base = base.where(User.email == user_email)

    if search:
        pattern = f"%{search}%"
        base = base.where(
            User.email.ilike(pattern)
            | UserRating.reference_id.ilike(pattern)
            | UserRating.comment.ilike(pattern)
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
    }
    sort_col = sort_col_map.get(sort_by, UserRating.created_at)
    if order == "asc":
        base = base.order_by(sort_col.asc())
    else:
        base = base.order_by(sort_col.desc())

    # Pagination
    offset = (page - 1) * page_size
    base = base.offset(offset).limit(page_size)

    result = await session.execute(base)
    rows = result.unique().all()
    items = [_rating_to_read(rating, user) for rating, user in rows]

    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/export", tags=["ratings"])
async def export_ratings(
    rating_type: Optional[str] = Query(None),
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Export all ratings as XLSX (superuser only)."""
    import openpyxl

    stmt = select(UserRating, User).outerjoin(User, UserRating.user_id == User.id)
    if rating_type and rating_type in VALID_RATING_TYPES:
        stmt = stmt.where(UserRating.rating_type == rating_type)
    stmt = stmt.order_by(UserRating.created_at.desc())

    result = await session.execute(stmt)
    rows = result.unique().all()

    wb = openpyxl.Workbook()
    ws = wb.active
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
    ]
    ws.append(headers)

    for rating, user in rows:
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
