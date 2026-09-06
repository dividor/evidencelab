"""LLM usage rollup routes for the admin "Token Usage" tab.

Aggregates ``user_activity`` rows by user or by user-group, bucketed by
day / week / month, with an optional activity-type filter and a date
range. Returns one row per (bucket, group) pair plus a totals object.

Per the agreed design:

- Anonymous activity (``user_id IS NULL``) is preserved as a synthetic
  ``(anonymous)`` row in both groupings.
- A user belonging to multiple groups contributes their tokens / cost
  to **every** group they belong to (acknowledged over-count, surfaced
  to admins as a UI note).
- Users with no group memberships fall into a synthetic ``(no group)``
  row when grouping by group.
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User
from ui.backend.auth.users import current_superuser

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Whitelists — never pass user input directly into SQL identifiers
# ---------------------------------------------------------------------------

_BUCKETS = {"day", "week", "month"}
_GROUP_BYS = {"user", "user_group"}
_SORT_KEYS = {
    "bucket_start",
    "group_label",
    "request_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
}
_VALID_ACTIVITY_TYPES = {
    "search",
    "heatmap",
    "chat",
    "assistant-basic",
    "assistant-deep-research",
    "brief",
    # Server-side recorded types (see ui/backend/services/usage_recorder.py).
    "highlight",
    "evaluation",
    "mcp-assistant",
    "a2a-assistant",
    "pipeline",
}

_DEFAULT_RANGE_DAYS = 30
_ANONYMOUS_LABEL = "(anonymous)"
_NO_GROUP_LABEL = "(no group)"


# ---------------------------------------------------------------------------
# Input validation / coercion
# ---------------------------------------------------------------------------


def _validate_bucket(bucket: str) -> str:
    if bucket not in _BUCKETS:
        raise HTTPException(
            status_code=422,
            detail=f"bucket must be one of: {sorted(_BUCKETS)}",
        )
    return bucket


def _validate_group_by(group_by: str) -> str:
    if group_by not in _GROUP_BYS:
        raise HTTPException(
            status_code=422,
            detail=f"group_by must be one of: {sorted(_GROUP_BYS)}",
        )
    return group_by


def _validate_activity_type(activity_type: Optional[str]) -> Optional[str]:
    if activity_type is None or activity_type == "":
        return None
    if activity_type not in _VALID_ACTIVITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"activity_type must be one of: {sorted(_VALID_ACTIVITY_TYPES)}",
        )
    return activity_type


def _resolve_date_range(
    from_date: Optional[date], to_date: Optional[date]
) -> Tuple[datetime, datetime]:
    """Default to the last ``_DEFAULT_RANGE_DAYS`` days, inclusive of today.

    Coerces to UTC-aware datetimes so the ``created_at`` comparison matches
    the timezone of the column. The ``to`` bound is exclusive (today + 1).
    """
    today = datetime.now(timezone.utc).date()
    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = to_date - timedelta(days=_DEFAULT_RANGE_DAYS)
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date must be <= to_date")
    start_dt = datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(
        to_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    return start_dt, end_dt


# ---------------------------------------------------------------------------
# SQL construction — values are parameterised; only whitelisted identifiers
# are interpolated.
# ---------------------------------------------------------------------------


def _activity_type_clause(activity_type: Optional[str]) -> str:
    """Inline JSONB filter; activity_type is validated against a whitelist.

    Mirrors the ActivityManager frontend semantics: a row's effective type
    is ``filters.type`` if set, otherwise ``filters.mode``, otherwise the
    default ``'search'``. Plain search rows are logged with no ``type``
    key at all, so a literal ``filters->>'type' = 'search'`` filter would
    return nothing — we use COALESCE to match the default-to-'search'
    behaviour the admin sees in the Activity tab.

    Value is bound via :activity_type; only structurally inlined here.
    """
    if not activity_type:
        return ""
    return (
        " AND COALESCE(ua.filters->>'type', ua.filters->>'mode', 'search')"
        " = :activity_type"
    )


def _build_user_grouped_sql(bucket: str, activity_type: Optional[str]) -> str:
    """Aggregation SQL for ``group_by=user``.

    ``bucket`` is whitelisted to {day, week, month} — safe to interpolate.
    All user input flows in via bound parameters.
    """
    extra_filter = _activity_type_clause(activity_type)
    return f"""
        SELECT
            date_trunc(:bucket, ua.created_at) AS bucket_start,
            COALESCE(u.email, '{_ANONYMOUS_LABEL}') AS group_key,
            COALESCE(
                NULLIF(TRIM(
                    COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')
                ), ''),
                u.email,
                '{_ANONYMOUS_LABEL}'
            ) AS group_label,
            COUNT(*) AS request_count,
            COALESCE(SUM(ua.prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(ua.completion_tokens), 0) AS completion_tokens,
            COALESCE(
                SUM(COALESCE(ua.prompt_tokens, 0)
                    + COALESCE(ua.completion_tokens, 0)),
                0
            ) AS total_tokens,
            COALESCE(SUM(ua.cost_usd), 0) AS cost_usd
        FROM user_activity ua
        LEFT JOIN users u ON u.id = ua.user_id
        WHERE ua.created_at >= :from_dt AND ua.created_at < :to_dt
              {extra_filter}
        GROUP BY 1, 2, 3
    """


def _build_group_grouped_sql(bucket: str, activity_type: Optional[str]) -> str:
    """Aggregation SQL for ``group_by=user_group``.

    A row is emitted once per (bucket, group) pair. A user belonging to
    N groups contributes their tokens to all N groups.
    """
    extra_filter = _activity_type_clause(activity_type)
    return f"""
        WITH expanded AS (
            -- Rows for each (activity, group) pair the user belongs to
            SELECT ua.created_at, ua.prompt_tokens, ua.completion_tokens,
                   ua.cost_usd, ug.id::text AS group_key, ug.name AS group_label
            FROM user_activity ua
            JOIN user_group_members ugm ON ugm.user_id = ua.user_id
            JOIN user_groups ug ON ug.id = ugm.group_id
            WHERE ua.user_id IS NOT NULL
              AND ua.created_at >= :from_dt AND ua.created_at < :to_dt
                  {extra_filter}
            UNION ALL
            -- Anonymous bucket
            SELECT ua.created_at, ua.prompt_tokens, ua.completion_tokens,
                   ua.cost_usd, '{_ANONYMOUS_LABEL}' AS group_key,
                   '{_ANONYMOUS_LABEL}' AS group_label
            FROM user_activity ua
            WHERE ua.user_id IS NULL
              AND ua.created_at >= :from_dt AND ua.created_at < :to_dt
                  {extra_filter}
            UNION ALL
            -- Users with no group memberships
            SELECT ua.created_at, ua.prompt_tokens, ua.completion_tokens,
                   ua.cost_usd, '{_NO_GROUP_LABEL}' AS group_key,
                   '{_NO_GROUP_LABEL}' AS group_label
            FROM user_activity ua
            WHERE ua.user_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM user_group_members ugm
                  WHERE ugm.user_id = ua.user_id
              )
              AND ua.created_at >= :from_dt AND ua.created_at < :to_dt
                  {extra_filter}
        )
        SELECT
            date_trunc(:bucket, created_at) AS bucket_start,
            group_key,
            group_label,
            COUNT(*) AS request_count,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(
                SUM(COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)),
                0
            ) AS total_tokens,
            COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM expanded
        GROUP BY 1, 2, 3
    """


# ---------------------------------------------------------------------------
# Row → response payload
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert a SQLAlchemy ``Row`` mapping into the response shape."""
    bucket_start = row.bucket_start
    if isinstance(bucket_start, datetime):
        bucket_start = bucket_start.date().isoformat()
    elif isinstance(bucket_start, date):
        bucket_start = bucket_start.isoformat()
    cost = row.cost_usd
    if isinstance(cost, Decimal):
        cost_value: Any = format(cost.quantize(Decimal("0.000001")), "f")
    else:
        cost_value = cost
    return {
        "bucket_start": bucket_start,
        "group_key": row.group_key,
        "group_label": row.group_label,
        "request_count": int(row.request_count),
        "prompt_tokens": int(row.prompt_tokens),
        "completion_tokens": int(row.completion_tokens),
        "total_tokens": int(row.total_tokens),
        "cost_usd": cost_value,
    }


def compute_totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum the numeric columns across already-bucketed rows."""
    totals_int = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    cost_total = Decimal(0)
    for r in rows:
        for k in totals_int:
            totals_int[k] += int(r[k])
        if r["cost_usd"] is not None:
            cost_total += Decimal(str(r["cost_usd"]))
    return {
        **totals_int,
        "cost_usd": format(cost_total.quantize(Decimal("0.000001")), "f"),
    }


def sort_rows(
    rows: List[Dict[str, Any]], sort_by: str, order: str
) -> List[Dict[str, Any]]:
    """Stable-sort rows in Python so the same logic powers JSON + XLSX."""
    if sort_by not in _SORT_KEYS:
        sort_by = "bucket_start"
    reverse = order != "asc"

    def key(r: Dict[str, Any]):
        v = r[sort_by]
        # Decimal-as-string costs sort lexicographically without coercion.
        if sort_by == "cost_usd" and v is not None:
            return Decimal(str(v))
        return v

    return sorted(rows, key=key, reverse=reverse)


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


async def _fetch_usage_rows(
    session: AsyncSession,
    bucket: str,
    group_by: str,
    from_dt: datetime,
    to_dt: datetime,
    activity_type: Optional[str],
) -> List[Dict[str, Any]]:
    """Run the appropriate SQL and return shaped row dicts."""
    if group_by == "user_group":
        sql = _build_group_grouped_sql(bucket, activity_type)
    else:
        sql = _build_user_grouped_sql(bucket, activity_type)
    params: Dict[str, Any] = {
        "bucket": bucket,
        "from_dt": from_dt,
        "to_dt": to_dt,
    }
    if activity_type:
        params["activity_type"] = activity_type
    result = await session.execute(text(sql), params)
    return [_row_to_dict(r) for r in result.mappings()]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/summary", tags=["llm-usage"])
async def llm_usage_summary(
    bucket: str = Query("week"),
    group_by: str = Query("user"),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    activity_type: Optional[str] = Query(None),
    sort_by: str = Query("bucket_start"),
    order: str = Query("desc"),
    _admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Return one row per (time-bucket, user-or-group) plus totals."""
    bucket = _validate_bucket(bucket)
    group_by = _validate_group_by(group_by)
    activity_type = _validate_activity_type(activity_type)
    from_dt, to_dt = _resolve_date_range(from_date, to_date)

    rows = await _fetch_usage_rows(
        session, bucket, group_by, from_dt, to_dt, activity_type
    )
    rows = sort_rows(rows, sort_by, order)
    totals = compute_totals(rows)

    return {
        "rows": rows,
        "totals": totals,
        "bucket": bucket,
        "group_by": group_by,
        "from_date": from_dt.date().isoformat(),
        "to_date": (to_dt - timedelta(days=1)).date().isoformat(),
        "activity_type": activity_type,
    }


@router.get("/export", tags=["llm-usage"])
async def llm_usage_export(
    bucket: str = Query("week"),
    group_by: str = Query("user"),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    activity_type: Optional[str] = Query(None),
    sort_by: str = Query("bucket_start"),
    order: str = Query("desc"),
    _admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Same query as ``/summary`` but returns an XLSX file."""
    import openpyxl

    bucket = _validate_bucket(bucket)
    group_by = _validate_group_by(group_by)
    activity_type = _validate_activity_type(activity_type)
    from_dt, to_dt = _resolve_date_range(from_date, to_date)

    rows = await _fetch_usage_rows(
        session, bucket, group_by, from_dt, to_dt, activity_type
    )
    rows = sort_rows(rows, sort_by, order)
    totals = compute_totals(rows)

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "LLM Usage"
    ws.append(
        [
            f"Bucket start ({bucket})",
            "User" if group_by == "user" else "Group",
            "Requests",
            "Prompt Tokens",
            "Completion Tokens",
            "Total Tokens",
            "Cost (USD)",
        ]
    )
    for r in rows:
        ws.append(
            [
                r["bucket_start"],
                r["group_label"],
                r["request_count"],
                r["prompt_tokens"],
                r["completion_tokens"],
                r["total_tokens"],
                float(r["cost_usd"]) if r["cost_usd"] is not None else None,
            ]
        )
    ws.append(
        [
            "TOTAL",
            "",
            totals["request_count"],
            totals["prompt_tokens"],
            totals["completion_tokens"],
            totals["total_tokens"],
            float(totals["cost_usd"]),
        ]
    )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"llm_usage_{group_by}_{bucket}_{stamp}.xlsx"
    return StreamingResponse(
        buf,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
