"""Server-side LLM usage recording into the ``user_activity`` table.

Historically token usage only reached ``user_activity`` when the browser
echoed the SSE ``done`` event's usage payload back through the activity
routes — anything not running in a browser tab (evaluation runs, MCP/A2A
tool calls) was invisible, and even browser paths depended on the client
cooperating. This module records usage **at the source**: the backend
writes (or accumulates onto) the activity row itself the moment an LLM
call finishes, so the admin "Token Usage" rollup sees every call.

Semantics:

- Rows are addressed by ``search_id`` and owner-scoped exactly like the
  client activity routes (``user_id`` first, then ``session_id``) so a
  client-supplied id can never write into another owner's row. Purely
  server-generated ids (evaluation runs, MCP calls) pass no owner and
  match on ``search_id`` alone.
- An existing row **accumulates** token counts and cost (multiple LLM
  calls — drill-down summaries, brief sections, judge calls — sum onto
  one row). Cost is computed per delta from the delta's own model so
  mixed-model accumulation stays accurate; ``llm_model`` keeps the most
  recent model as a label.
- Recording is fire-and-forget by design (same contract as the activity
  routes' "non-critical" client logging and the MCP audit log): a
  failure to record usage must never break the user-facing call that
  spent the tokens, so errors are logged server-side and swallowed.
"""

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional, Set

from sqlalchemy import select

from ui.backend.auth.db import async_session_factory
from ui.backend.auth.models import UserActivity
from ui.backend.utils.llm_costs import compute_cost

logger = logging.getLogger(__name__)

# Strong references to in-flight background recording tasks so they are not
# garbage-collected mid-write (asyncio only keeps weak refs to tasks).
_background_tasks: Set["asyncio.Task[Any]"] = set()

# Mirror the ActivityCreate schema bounds so server-recorded rows respect
# the same limits as client-logged ones.
_MAX_QUERY_CHARS = 5000
_MAX_TOKENS = 10_000_000


def usage_cost(usage: Dict[str, Any]) -> Optional[Decimal]:
    """Cost in USD for one usage payload, or None when the model has no rate."""
    return compute_cost(
        usage.get("llm_model"),
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )


def _clean_tokens(value: Any) -> Optional[int]:
    """Coerce a token count to a bounded non-negative int, else None."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if count < 0:
        return None
    return min(count, _MAX_TOKENS)


def has_usage(usage: Optional[Dict[str, Any]]) -> bool:
    """True when the payload carries at least one token count."""
    if not usage:
        return False
    return bool(
        _clean_tokens(usage.get("prompt_tokens"))
        or _clean_tokens(usage.get("completion_tokens"))
    )


def _accumulate_usage(row: Any, usage: Dict[str, Any], cost: Optional[Decimal]) -> None:
    """Add a usage delta (tokens + its own cost) onto an existing row."""
    prompt = _clean_tokens(usage.get("prompt_tokens"))
    completion = _clean_tokens(usage.get("completion_tokens"))
    if prompt:
        row.prompt_tokens = (row.prompt_tokens or 0) + prompt
    if completion:
        row.completion_tokens = (row.completion_tokens or 0) + completion
    if usage.get("llm_model"):
        row.llm_model = str(usage["llm_model"])[:128]
    if cost is not None:
        row.cost_usd = (row.cost_usd or Decimal(0)) + cost


async def _find_row(
    session: Any,
    search_uuid: uuid.UUID,
    user_id: Optional[uuid.UUID],
    session_id: Optional[str],
    server_owned: bool,
) -> Optional[UserActivity]:
    """Owner-scoped lookup, mirroring the client activity routes' upsert key.

    A row is matched on ``search_id`` alone only for *server-generated* ids
    (``server_owned=True`` — evaluation runs, MCP calls). Client-supplied ids
    with no owner context never match, so an anonymous caller cannot
    accumulate usage onto (or relabel the model of) another owner's row by
    guessing its search id — their usage lands on a fresh row instead.

    The row is locked (``FOR UPDATE``) so concurrent accumulations — e.g.
    parallel highlight calls for one search — serialize instead of losing
    deltas to a read-modify-write race.
    """
    stmt = select(UserActivity).where(UserActivity.search_id == search_uuid)
    if user_id is not None:
        stmt = stmt.where(UserActivity.user_id == user_id)
    elif session_id:
        stmt = stmt.where(UserActivity.session_id == session_id)
    elif not server_owned:
        return None
    result = await session.execute(stmt.with_for_update())
    return result.scalars().first()


def _build_row(
    *,
    search_uuid: uuid.UUID,
    activity_type: Optional[str],
    query: str,
    user_id: Optional[uuid.UUID],
    session_id: Optional[str],
    filters_extra: Optional[Dict[str, Any]],
    usage: Dict[str, Any],
    cost: Optional[Decimal],
) -> UserActivity:
    """Build a fresh activity row for a usage record with no existing row."""
    filters: Dict[str, Any] = dict(filters_extra or {})
    if activity_type:
        filters["type"] = activity_type
    row = UserActivity(
        user_id=user_id,
        session_id=session_id if user_id is None else None,
        search_id=search_uuid,
        query=query[:_MAX_QUERY_CHARS],
        filters=filters or None,
    )
    _accumulate_usage(row, usage, cost)
    return row


def _coerce_search_id(search_id: Any) -> Optional[uuid.UUID]:
    """Parse the caller's search/activity id; None when absent or invalid."""
    if search_id is None:
        return None
    if isinstance(search_id, uuid.UUID):
        return search_id
    try:
        return uuid.UUID(str(search_id))
    except ValueError:
        logger.warning("record_llm_usage: invalid search_id %r ignored", search_id)
        return None


async def record_llm_usage(
    *,
    usage: Optional[Dict[str, Any]],
    activity_type: Optional[str],
    query: str,
    user_id: Optional[uuid.UUID] = None,
    session_id: Optional[str] = None,
    search_id: Any = None,
    filters_extra: Optional[Dict[str, Any]] = None,
    cost_usd: Optional[Decimal] = None,
    server_owned: bool = False,
    session_factory: Any = None,
) -> bool:
    """Record one LLM usage delta into ``user_activity`` (fire-and-forget).

    Args:
        usage: ``{llm_model?, prompt_tokens?, completion_tokens?}`` — the
            shape produced by ``summarize_usage_metadata``. Skipped when it
            carries no token counts.
        activity_type: ``filters.type`` for a newly created row (existing
            rows keep their filters untouched). ``None`` means the default
            ``search`` type.
        query: Row label when a new row is created.
        user_id / session_id: Owner scoping for the row lookup.
        search_id: Activity row key (str or UUID). Absent/invalid → a fresh
            row under a random id (the usage is still never dropped).
        filters_extra: Extra context merged into a new row's filters JSONB.
        cost_usd: Pre-computed cost for this delta; when None the cost is
            derived from the usage payload's model + token counts.
        server_owned: True only for server-generated ids (evaluation runs,
            MCP calls) — allows matching an existing row on ``search_id``
            alone. Client-supplied ids without owner context get a fresh
            row instead (see ``_find_row``).
        session_factory: Injectable async session factory (tests).

    Returns:
        True when a row was written, False when skipped or failed.
    """
    if usage is None or not has_usage(usage):
        return False
    try:
        search_uuid = _coerce_search_id(search_id) or uuid.uuid4()
        cost = cost_usd if cost_usd is not None else usage_cost(usage)
        factory = session_factory or async_session_factory
        async with factory() as session:
            row = await _find_row(
                session, search_uuid, user_id, session_id, server_owned
            )
            if row is not None:
                _accumulate_usage(row, usage, cost)
            else:
                session.add(
                    _build_row(
                        search_uuid=search_uuid,
                        activity_type=activity_type,
                        query=query,
                        user_id=user_id,
                        session_id=session_id,
                        filters_extra=filters_extra,
                        usage=usage,
                        cost=cost,
                    )
                )
            await session.commit()
        return True
    except Exception:  # pragma: no cover - defensive: never break the caller
        logger.warning("Failed to record LLM usage", exc_info=True)
        return False


def schedule_llm_usage_recording(**kwargs: Any) -> None:
    """Schedule ``record_llm_usage`` as a fire-and-forget background task.

    Used by request/stream handlers so recording never adds latency to — and
    can never fail — a product path: the DB write happens off the request,
    after the response/stream has moved on (mirrors the MCP audit log
    pattern). Never raises; a task reference is retained until completion so
    the write cannot be garbage-collected mid-flight.
    """
    try:
        task = asyncio.get_running_loop().create_task(record_llm_usage(**kwargs))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except Exception:  # pragma: no cover - defensive: never break the caller
        logger.warning("Could not schedule LLM usage recording", exc_info=True)
