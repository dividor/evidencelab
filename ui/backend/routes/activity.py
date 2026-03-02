"""Activity routes — log search activity, append summary; admin list & export."""

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User, UserActivity, UserRating
from ui.backend.auth.schemas import ActivityCreate, ActivityRead, ActivitySummaryUpdate
from ui.backend.auth.users import current_active_user, current_superuser

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _activity_to_read(activity: UserActivity, user: User | None = None) -> ActivityRead:
    """Convert a UserActivity ORM object to an ActivityRead response."""
    return ActivityRead(
        id=activity.id,
        user_id=activity.user_id,
        user_email=user.email if user else None,
        user_display_name=user.display_name if user else None,
        search_id=activity.search_id,
        query=activity.query,
        filters=activity.filters,
        search_results=activity.search_results,
        ai_summary=activity.ai_summary,
        url=activity.url,
        has_ratings=activity.has_ratings,
        created_at=activity.created_at,
    )


# JSONB sort keys that need nullslast() handling
_JSONB_SORT_KEYS = {"search_time", "summary_time", "heatmap_time"}

# Mapping of sort_by parameter values → SQLAlchemy column expressions
_SORT_COL_MAP = {
    "created_at": lambda: UserActivity.created_at,
    "query": lambda: UserActivity.query,
    "user_email": lambda: User.email,
    "has_ratings": lambda: UserActivity.has_ratings,
    "search_time": lambda: UserActivity.filters["timing"][
        "search_duration_ms"
    ].astext.cast(Float),
    "summary_time": lambda: UserActivity.filters["timing"][
        "summary_duration_ms"
    ].astext.cast(Float),
    "heatmap_time": lambda: UserActivity.filters["timing"][
        "heatmap_duration_ms"
    ].astext.cast(Float),
}


def _apply_activity_sorting(stmt, sort_by: str, order: str):
    """Apply sorting to an activity list query."""
    col_factory = _SORT_COL_MAP.get(sort_by)
    sort_col = col_factory() if col_factory else UserActivity.created_at
    expr = sort_col.asc() if order == "asc" else sort_col.desc()
    if sort_by in _JSONB_SORT_KEYS:
        expr = expr.nullslast()
    return stmt.order_by(expr)


def _build_activity_items(rows: list, rated_ids: set[str]) -> list[dict]:
    """Build activity response dicts with live has_ratings enrichment."""
    items = []
    for activity, user in rows:
        item = _activity_to_read(activity, user)
        if str(activity.search_id) in rated_ids:
            item.has_ratings = True
        items.append(item.model_dump(mode="json"))
    return items


def _ms_to_seconds(ms: float | None) -> float | None:
    """Convert milliseconds to seconds rounded to 2 decimals, or None."""
    return round(ms / 1000, 2) if ms else None


def _count_search_results(activity: UserActivity) -> int:
    """Count search results from either list or dict format."""
    sr = activity.search_results
    if sr and isinstance(sr, list):
        return len(sr)
    if sr and isinstance(sr, dict):
        return len(sr.get("results", []))
    return 0


def _build_export_row(activity: UserActivity, user: User | None) -> list:
    """Build a single XLSX export row from an activity + user pair."""
    summary_text = activity.ai_summary or ""
    if len(summary_text) > 1000:
        summary_text = summary_text[:997] + "..."

    timing = (activity.filters or {}).get("timing", {})
    created = (
        activity.created_at.strftime("%Y-%m-%d %H:%M") if activity.created_at else ""
    )
    return [
        created,
        user.email if user else "",
        user.display_name if user else "",
        activity.query,
        _count_search_results(activity),
        _ms_to_seconds(timing.get("search_duration_ms")),
        _ms_to_seconds(timing.get("summary_duration_ms")),
        _ms_to_seconds(timing.get("heatmap_duration_ms")),
        summary_text,
        activity.url or "",
        "Yes" if activity.has_ratings else "No",
        str(activity.search_id),
    ]


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=ActivityRead, tags=["activity"])
async def log_activity(
    body: ActivityCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Log a search activity event (fire-and-forget from the frontend)."""
    try:
        search_uuid = uuid.UUID(body.search_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="search_id must be a valid UUID")

    activity = UserActivity(
        user_id=user.id,
        search_id=search_uuid,
        query=body.query,
        filters=body.filters,
        search_results=body.search_results,
        ai_summary=body.ai_summary,
        url=body.url,
    )
    session.add(activity)
    await session.commit()
    await session.refresh(activity)
    return _activity_to_read(activity, user)


@router.patch("/{search_id}/summary", response_model=ActivityRead, tags=["activity"])
async def update_activity_summary(
    search_id: uuid.UUID,
    body: ActivitySummaryUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Append / replace the AI summary on an existing activity record.

    Called after the AI summary stream finishes so we can capture the
    full summary text.
    """
    result = await session.execute(
        select(UserActivity).where(
            UserActivity.user_id == user.id,
            UserActivity.search_id == search_id,
        )
    )
    activity = result.scalars().first()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity record not found")
    if body.ai_summary is not None:
        activity.ai_summary = body.ai_summary

    # Merge timing & drilldown tree into existing filters JSONB
    if body.summary_duration_ms is not None or body.drilldown_tree is not None:
        merged = dict(activity.filters or {})
        if body.summary_duration_ms is not None:
            timing = merged.get("timing", {})
            timing["summary_duration_ms"] = body.summary_duration_ms
            merged["timing"] = timing
        if body.drilldown_tree is not None:
            merged["drilldown_tree"] = body.drilldown_tree
        activity.filters = merged

    await session.commit()
    await session.refresh(activity)
    return _activity_to_read(activity, user)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/all", tags=["activity"])
async def list_all_activity(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    user_email: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """List all user activity with pagination (superuser only)."""
    base = select(UserActivity, User).outerjoin(User, UserActivity.user_id == User.id)

    if search:
        pattern = f"%{search}%"
        base = base.where(User.email.ilike(pattern) | UserActivity.query.ilike(pattern))

    if user_email:
        base = base.where(User.email == user_email)

    # Count total
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    # Sorting
    base = _apply_activity_sorting(base, sort_by, order)

    # Pagination
    offset = (page - 1) * page_size
    base = base.offset(offset).limit(page_size)

    result = await session.execute(base)
    rows = result.unique().all()

    # Dynamically compute has_ratings from the ratings table
    # (fixes stale flags from the old searchId mismatch bug)
    rated_ids = await _get_rated_search_ids(session, rows)

    return {
        "items": _build_activity_items(rows, rated_ids),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _get_rated_search_ids(
    session: AsyncSession,
    rows: list,
) -> set[str]:
    """Return set of search_id strings that have at least one rating."""
    search_ids = [str(a.search_id) for a, _u in rows]
    if not search_ids:
        return set()
    rated_result = await session.execute(
        select(UserRating.reference_id)
        .where(
            UserRating.reference_id.in_(search_ids),
            UserRating.rating_type.in_(["search_result", "ai_summary"]),
        )
        .distinct()
    )
    return {r[0] for r in rated_result}


@router.get("/export", tags=["activity"])
async def export_activity(
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Export all activity as XLSX (superuser only)."""
    import openpyxl

    stmt = (
        select(UserActivity, User)
        .outerjoin(User, UserActivity.user_id == User.id)
        .order_by(UserActivity.created_at.desc())
    )

    result = await session.execute(stmt)
    rows = result.unique().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Activity"
    headers = [
        "Date",
        "User Email",
        "User Name",
        "Query",
        "# Results",
        "Search Time (s)",
        "Summary Time (s)",
        "Heatmap Time (s)",
        "AI Summary",
        "URL",
        "Has Ratings",
        "Search ID",
    ]
    ws.append(headers)

    for activity, user in rows:
        ws.append(_build_export_row(activity, user))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = (
        f"activity_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
