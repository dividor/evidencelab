"""Activity routes — log search activity, append summary; admin list & export."""

import copy
import io
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Float, Numeric, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User, UserActivity, UserRating
from ui.backend.auth.schemas import (
    ActivityCreate,
    ActivityRead,
    ActivitySummaryUpdateAnonymous,
)
from ui.backend.auth.users import current_superuser, optional_current_user
from ui.backend.utils.llm_costs import compute_cost

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _activity_to_read(activity: UserActivity, user: User | None = None) -> ActivityRead:
    """Convert a UserActivity ORM object to an ActivityRead response."""
    display_name = None
    if user:
        display_name = user.full_name
    elif not activity.user_id:
        display_name = "Anonymous"

    return ActivityRead(
        id=activity.id,
        user_id=activity.user_id,
        session_id=activity.session_id,
        user_email=user.email if user else None,
        user_display_name=display_name,
        search_id=activity.search_id,
        query=activity.query,
        filters=activity.filters,
        search_results=activity.search_results,
        ai_summary=activity.ai_summary,
        url=activity.url,
        has_ratings=activity.has_ratings,
        created_at=activity.created_at,
        llm_model=activity.llm_model,
        prompt_tokens=activity.prompt_tokens,
        completion_tokens=activity.completion_tokens,
        cost_usd=activity.cost_usd,
    )


def _resolve_cost(
    submitted: Optional[Decimal],
    model: Optional[str],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
) -> Optional[Decimal]:
    """Prefer the server-computed cost over a client-submitted value.

    Clients can submit usage; the server is authoritative for cost so we
    can't be billed wrong amounts by tampered payloads. Falls back to the
    client value when the server has no rate for the model.
    """
    server = compute_cost(model, prompt_tokens, completion_tokens)
    if server is not None:
        return server
    return submitted


async def _find_existing_activity(
    session: AsyncSession,
    user: User | None,
    session_id: Optional[str],
    search_uuid: uuid.UUID,
) -> Optional[UserActivity]:
    """Find an activity row by its owner (user or anonymous session) and
    search_id, or None. Owner-scoped so users can't read/overwrite each other."""
    if user:
        stmt = select(UserActivity).where(
            UserActivity.user_id == user.id,
            UserActivity.search_id == search_uuid,
        )
    elif session_id:
        stmt = select(UserActivity).where(
            UserActivity.session_id == session_id,
            UserActivity.search_id == search_uuid,
        )
    else:
        return None
    result = await session.execute(stmt)
    return result.scalars().first()


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
    "llm_model": lambda: UserActivity.llm_model,
    "total_tokens": lambda: (
        func.coalesce(UserActivity.prompt_tokens, 0)
        + func.coalesce(UserActivity.completion_tokens, 0)
    ).cast(Numeric),
    "cost_usd": lambda: UserActivity.cost_usd,
}

# Columns that may be NULL for old rows; we want nullslast on DESC and
# asc-with-nulls-last when sorted ascending so unknown values cluster at
# the bottom rather than dominating the page.
_NULLABLE_SORT_KEYS = _JSONB_SORT_KEYS | {"llm_model", "total_tokens", "cost_usd"}


def _apply_activity_sorting(stmt, sort_by: str, order: str):
    """Apply sorting to an activity list query."""
    col_factory = _SORT_COL_MAP.get(sort_by)
    sort_col = col_factory() if col_factory else UserActivity.created_at
    expr = sort_col.asc() if order == "asc" else sort_col.desc()
    if sort_by in _NULLABLE_SORT_KEYS:
        expr = expr.nullslast()
    return stmt.order_by(expr)


def _build_activity_items(rows: Sequence, rated_ids: set[str]) -> list[dict]:
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
    cost = activity.cost_usd
    return [
        created,
        user.email if user else "(anonymous)",
        user.full_name if user else "Anonymous",
        activity.query,
        _count_search_results(activity),
        _ms_to_seconds(timing.get("search_duration_ms")),
        _ms_to_seconds(timing.get("summary_duration_ms")),
        _ms_to_seconds(timing.get("heatmap_duration_ms")),
        activity.llm_model or "",
        activity.prompt_tokens,
        activity.completion_tokens,
        float(cost) if cost is not None else None,
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
    user: User | None = Depends(optional_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Log a search activity event (fire-and-forget from the frontend).

    Works for both authenticated users (user_id stored) and anonymous
    visitors (session_id stored).
    """
    try:
        search_uuid = uuid.UUID(body.search_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="search_id must be a valid UUID")

    cost = _resolve_cost(
        body.cost_usd,
        body.llm_model,
        body.prompt_tokens,
        body.completion_tokens,
    )

    # Upsert by (owner, search_id): update an existing row in place, otherwise
    # insert. Searches use a fresh search_id each time, so they always insert;
    # the Brief tab reuses one stable search_id per brief, so re-logging it on
    # each save updates the same activity row rather than creating duplicates.
    existing = await _find_existing_activity(
        session, user, body.session_id, search_uuid
    )
    if existing is not None:
        # search_results is JSONB holding a list; the typed-but-loose
        # constructor accepts it on insert, so mutate through an Any alias to
        # keep the same loose typing on the update path.
        row: Any = existing
        row.query = body.query
        row.filters = body.filters
        row.search_results = body.search_results
        if body.ai_summary is not None:
            row.ai_summary = body.ai_summary
        row.url = body.url
        # Usage is patch-only: token counts may already have been recorded
        # server-side (streaming endpoints, brief sections), so a re-POST
        # without usage — e.g. every Brief save — must not null them out.
        _apply_token_usage(row, body)
        activity = existing
    else:
        activity = UserActivity(
            user_id=user.id if user else None,
            session_id=body.session_id if not user else None,
            search_id=search_uuid,
            query=body.query,
            filters=body.filters,
            search_results=body.search_results,
            ai_summary=body.ai_summary,
            url=body.url,
            llm_model=body.llm_model,
            prompt_tokens=body.prompt_tokens,
            completion_tokens=body.completion_tokens,
            cost_usd=cost,
        )
        session.add(activity)
    await session.commit()
    await session.refresh(activity)
    return _activity_to_read(activity, user)


@router.patch("/{search_id}/summary", response_model=ActivityRead, tags=["activity"])
async def update_activity_summary(
    search_id: uuid.UUID,
    body: ActivitySummaryUpdateAnonymous,
    user: User | None = Depends(optional_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Append / replace the AI summary on an existing activity record.

    Called after the AI summary stream finishes so we can capture the
    full summary text.  Works for both authenticated and anonymous users.
    """
    if user:
        stmt = select(UserActivity).where(
            UserActivity.user_id == user.id,
            UserActivity.search_id == search_id,
        )
    elif body.session_id:
        stmt = select(UserActivity).where(
            UserActivity.session_id == body.session_id,
            UserActivity.search_id == search_id,
        )
    else:
        raise HTTPException(
            status_code=401, detail="Authentication or session_id required"
        )

    result = await session.execute(stmt)
    activity = result.scalars().first()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity record not found")

    _apply_summary_fields(activity, body)
    _merge_filters_update(activity, body)
    _apply_token_usage(activity, body)

    await session.commit()
    await session.refresh(activity)
    return _activity_to_read(activity, user)


def _apply_summary_fields(activity: UserActivity, body) -> None:
    """Copy the ai_summary text onto *activity* when provided."""
    if body.ai_summary is not None:
        activity.ai_summary = body.ai_summary


def _merge_filters_update(activity: UserActivity, body) -> None:
    """Merge timing & drilldown_tree into the filters JSONB column.

    Deep-copies the existing dict so SQLAlchemy sees the mutation (a
    shallow copy shares nested dicts and the ORM may skip the UPDATE).
    """
    if body.summary_duration_ms is None and body.drilldown_tree is None:
        return
    merged = copy.deepcopy(activity.filters or {})
    if body.summary_duration_ms is not None:
        timing = merged.get("timing", {})
        timing["summary_duration_ms"] = body.summary_duration_ms
        merged["timing"] = timing
    if body.drilldown_tree is not None:
        merged["drilldown_tree"] = body.drilldown_tree
    activity.filters = merged


def _apply_token_usage(activity: UserActivity, body) -> None:
    """Persist optional LLM usage and cost fields from *body*.

    Server recomputes ``cost_usd`` from the token counts when a rate is
    configured (see ``_resolve_cost``) so a tampered client value can't
    poison the admin spend view.
    """
    if body.llm_model is not None:
        activity.llm_model = body.llm_model
    if body.prompt_tokens is not None:
        activity.prompt_tokens = body.prompt_tokens
    if body.completion_tokens is not None:
        activity.completion_tokens = body.completion_tokens
    if (
        body.llm_model is not None
        or body.prompt_tokens is not None
        or body.completion_tokens is not None
        or body.cost_usd is not None
    ):
        activity.cost_usd = _resolve_cost(
            body.cost_usd,
            activity.llm_model,
            activity.prompt_tokens,
            activity.completion_tokens,
        )


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
    base = select(UserActivity, User).outerjoin(
        User, UserActivity.user_id == User.id  # type: ignore[arg-type]
    )

    if search:
        pattern = f"%{search}%"
        base = base.where(  # type: ignore[arg-type]
            User.email.ilike(pattern)  # type: ignore[attr-defined]
            | UserActivity.query.ilike(pattern)  # type: ignore[attr-defined]
        )

    if user_email:
        base = base.where(User.email == user_email)  # type: ignore[arg-type]

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
    rows: Sequence,
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
    assert ws is not None
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
        "Model",
        "Prompt Tokens",
        "Completion Tokens",
        "Cost (USD)",
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
