"""A daily ceiling on what the site's AI features may cost.

``AI_DAILY_COST_LIMIT_USD`` is the most the site's AI features may cost in
one UTC day, in US dollars, priced as the admin Token Usage tab prices them
(``ui.backend.utils.llm_costs``). Unset means no ceiling; ``0`` turns the AI
features off. Once the day's total reaches it, every AI request is refused
with :data:`LIMIT_MESSAGE` until 00:00 UTC, while search, browsing and
keyword highlighting keep working. Administrators are not exempt: raise the
setting instead.

What counts: every AI call recorded through
``ui.backend.services.usage_recorder`` — the website's AI features, the admin
test runs and the MCP and A2A assistant — added to ``ai_daily_spend`` as the
usage is recorded. Pipeline runs record their usage separately and are
neither counted nor stopped, because stopping one midway would mark its
documents failed; Bedrock usage alarms cover them on AWS.

A call is priced by the ``supported_llms`` key of the model it used, however
the request named that model (by key, by the provider's model id, or not at
all, which means the default model). With a limit set, the api and the
MCP/A2A server refuse to start while a model config.json can send AI calls
to has no price, because its calls would add nothing to the day's total and
the limit would never stop them. A call that still cannot be priced is logged
as an error (:data:`UNPRICED_CALL_LOG`).

The total is read at most every :data:`CACHE_SECONDS` per process, and a
call's cost is recorded when the call finishes, so calls already running or
started within that window can take the day somewhat past the limit.
"""

from __future__ import annotations

import logging
import math
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from pipeline.db import config as db_config
from ui.backend.auth.models import AiDailySpend
from ui.backend.utils.llm_costs import has_cost_data
from utils.llm_factory import default_model_name, supported_llm_key

logger = logging.getLogger(__name__)

LIMIT_ENV = "AI_DAILY_COST_LIMIT_USD"

# Where a model's price goes, named in the start-up error.
PRICES_FILE = "ui/backend/utils/llm_costs.py"

# Starts the error logged for each AI call the limit could not price.
UNPRICED_CALL_LOG = "AI call not counted towards the daily AI limit"

# Where config.json's default model is set (``utils.llm_factory``).
_DEFAULT_MODEL_PLACE = "default model in config.json's application section"

# The model combo stages that name a chat model.
_COMBO_STAGES = (
    "summarization_model",
    "semantic_highlighting_model",
    "assistant_model",
    "judge_model",
)

LIMIT_MESSAGE = (
    "Today's AI allowance for this site has been used. Search still works; "
    "AI features return at 00:00 UTC."
)

# Logged once a day per process when the first request is refused. On AWS a
# CloudWatch metric filter matches this text to email the alert addresses.
LIMIT_REACHED_LOG = "AI daily limit reached"

CACHE_SECONDS = 30.0

_cache: dict[str, Any] = {"day": None, "spent": Decimal(0), "read_at": -math.inf}
_logged_day: Optional[date] = None


class AiDailyLimitReached(Exception):
    """The day's AI cost has reached ``AI_DAILY_COST_LIMIT_USD``."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(LIMIT_MESSAGE)
        self.retry_after_seconds = retry_after_seconds


def daily_limit() -> Optional[Decimal]:
    """The configured limit in US dollars, or None when no limit is set.

    Raises:
        ValueError: when the setting is not a number of dollars, 0 or more.
    """
    raw = os.environ.get(LIMIT_ENV, "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(
            f"{LIMIT_ENV} must be a number of US dollars, such as 25, not {raw!r}"
        ) from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{LIMIT_ENV} must be 0 or more, not {raw!r}")
    return value


def _stage_model(settings: Any) -> Optional[str]:
    """The model a combo stage names: ``{"model": ...}`` or a bare name."""
    model = settings.get("model") if isinstance(settings, dict) else settings
    return str(model) if model else None


def _named_models() -> List[tuple[str, str]]:
    """(model name, where it is set) for every model AI calls can be sent to."""
    named = [(key, "supported_llms") for key in db_config.SUPPORTED_LLMS]
    for combo_name, combo in db_config.UI_MODEL_COMBOS.items():
        for stage in _COMBO_STAGES:
            model = _stage_model(combo.get(stage))
            if model:
                named.append((model, f"ui_model_combos.{combo_name}.{stage}"))
    default = default_model_name()
    if default:
        place = "LLM_MODEL" if os.environ.get("LLM_MODEL") else _DEFAULT_MODEL_PLACE
        named.append((default, place))
    return named


def configured_llm_names() -> Dict[str, List[str]]:
    """Every model AI calls can be sent to, by the key its use is priced under.

    The ``supported_llms`` keys, the model each ``ui_model_combos`` stage names
    (the name the web interface sends) and the default model, each resolved to
    its ``supported_llms`` key as usage is labelled; a name config.json does
    not list stays as it is. Each maps to the places it is set.
    """
    places: Dict[str, List[str]] = {}
    for name, place in _named_models():
        places.setdefault(supported_llm_key(name) or name, []).append(place)
    return places


def unpriced_llm_names() -> Dict[str, List[str]]:
    """The models in :func:`configured_llm_names` with no price in ``llm_costs.py``."""
    return {
        name: where
        for name, where in configured_llm_names().items()
        if not has_cost_data(name)
    }


def _unpriced_message(unpriced: Dict[str, List[str]]) -> str:
    listed = "; ".join(
        f"{name} ({', '.join(where)})" for name, where in sorted(unpriced.items())
    )
    return (
        f"{LIMIT_ENV} is set, but config.json uses models that have no price, so "
        f"the limit would not count their use: {listed}. Give each a "
        '"price_per_million": {"input": <USD>, "output": <USD>} in its '
        f"supported_llms entry, or add it to LLM_COSTS_PER_1K in {PRICES_FILE} "
        "under its supported_llms key, or stop using it where listed."
    )


def report_unpriced_call(model: Optional[str]) -> None:
    """Log an error for an AI call that used tokens but has no price.

    Only with a limit set: the call is then missing from the day's total. With
    no limit, an unpriced model is expected (the Token Usage tab shows "—").
    """
    if daily_limit() is None:
        return
    logger.error(
        "%s: the call to %s has no price in config.json or %s, so the day's total (%s) "
        "does not include it",
        UNPRICED_CALL_LOG,
        model or "an unnamed model",
        PRICES_FILE,
        LIMIT_ENV,
    )


def validate_ai_daily_limit_setting() -> None:
    """Refuse to start with a limit that is malformed or cannot be counted.

    Called when the api and the MCP/A2A server start, so a typo, or a model
    whose use the limit would not count, fails the deploy instead of being
    found later. Does nothing when no limit is set.

    Raises:
        ValueError: when the setting is not a number of dollars, 0 or more, or
            when a limit is set and a model in config.json has no price.
    """
    limit = daily_limit()
    if limit is None:
        return
    unpriced = unpriced_llm_names()
    if unpriced:
        raise ValueError(_unpriced_message(unpriced))
    logger.info("%s: %s US dollars a day", LIMIT_ENV, limit)


def utc_today(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()


def seconds_until_utc_midnight(now: datetime) -> int:
    """Whole seconds from ``now`` to the next 00:00 UTC, at least 1."""
    now_utc = now.astimezone(timezone.utc)
    midnight = datetime.combine(
        now_utc.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    return max(1, math.ceil((midnight - now_utc).total_seconds()))


async def add_to_daily_spend(
    session: Any, cost_usd: Decimal, now: Optional[datetime] = None
) -> None:
    """Add one call's cost to its UTC day's total, in the caller's transaction."""
    if cost_usd <= 0:
        return
    stamp = now or datetime.now(timezone.utc)
    stmt = pg_insert(AiDailySpend).values(
        id=uuid.uuid4(), day=utc_today(stamp), cost_usd=cost_usd, updated_at=stamp
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ai_daily_spend_day",
        set_={
            "cost_usd": AiDailySpend.cost_usd + stmt.excluded.cost_usd,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)


async def spent_on(session: Any, day: date) -> Decimal:
    """The AI cost recorded for ``day``; 0 when nothing was recorded."""
    result = await session.execute(
        select(AiDailySpend.cost_usd).where(AiDailySpend.day == day)
    )
    spent = result.scalar_one_or_none()
    return Decimal(spent) if spent is not None else Decimal(0)


async def _cached_spent(
    day: date, session_factory: Callable[[], Any], clock: Callable[[], float]
) -> Decimal:
    fresh = _cache["day"] == day and clock() - _cache["read_at"] < CACHE_SECONDS
    if fresh:
        return _cache["spent"]
    async with session_factory() as session:
        spent = await spent_on(session, day)
    _cache.update(day=day, spent=spent, read_at=clock())
    return spent


def _log_limit_reached(day: date, spent: Decimal, limit: Decimal) -> None:
    global _logged_day
    if _logged_day == day:
        return
    _logged_day = day
    logger.warning(
        "%s: %s US dollars spent of %s on %s (UTC); AI features are paused "
        "until 00:00 UTC (%s)",
        LIMIT_REACHED_LOG,
        spent,
        limit,
        day.isoformat(),
        LIMIT_ENV,
    )


async def check_ai_allowance(
    *,
    session_factory: Optional[Callable[[], Any]] = None,
    now: Optional[datetime] = None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Raise :class:`AiDailyLimitReached` once today's AI cost reaches the limit.

    Does nothing when no limit is set.
    """
    limit = daily_limit()
    if limit is None:
        return
    current = now or datetime.now(timezone.utc)
    day = utc_today(current)
    if session_factory is None:
        from ui.backend.auth.db import async_session_factory

        session_factory = async_session_factory
    spent = await _cached_spent(day, session_factory, clock)
    if spent < limit:
        return
    _log_limit_reached(day, spent, limit)
    raise AiDailyLimitReached(seconds_until_utc_midnight(current))


async def require_ai_allowance() -> None:
    """FastAPI dependency for routes that call an AI model."""
    await check_ai_allowance()


async def ai_daily_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """Answer 429 with the plain message and when to try again.

    Registered for :class:`AiDailyLimitReached` only.
    """
    if not isinstance(exc, AiDailyLimitReached):
        raise exc
    return JSONResponse(
        {"detail": str(exc)},
        status_code=429,
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )
