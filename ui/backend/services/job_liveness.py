"""Liveness of background jobs that run inside one api process while several
api copies share the database.

Brief citation checks and experiment runs execute as in-process background
tasks. Every cloud layout runs two or more api replicas against one Postgres
(see ``docs/admin/cloud-deployment.md``), so "the api started, therefore any
running row is orphaned" is wrong: a replica starting up says nothing about
the replica that owns the job. Instead, the owner stamps each progress write
with the time, and a job counts as orphaned only when it has shown no
progress for ``STALE_AFTER``. The owner writes only while the row still says
it is running, so a job that someone else failed (a cancel, or a recovery)
keeps that record, and a failed job never comes back to life.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import update

# A judged passage arrives every ~12 s at the default Vertex rate limit and a
# single model call is capped at 240 s, so a quarter of an hour of silence
# means the task is gone, not slow.
STALE_AFTER = timedelta(minutes=15)


async def write_while(
    session: Any, model: Any, row_id: Any, statuses: Iterable[str], **values: Any
) -> bool:
    """Write ``values`` to the job's row only while its ``status`` is one of
    ``statuses``, committing them together with whatever the session has
    pending. Returns False, with the pending work rolled back, when another
    writer (a cancel, or orphan recovery on another api copy) changed the
    status first: that writer's record stands and the caller must stop.

    The session's own copy of the row is left as it was (no synchronisation):
    after a rollback its attributes are expired, so callers keep the ids they
    need in local variables and never read the row again."""
    result = await session.execute(
        update(model)
        .where(model.id == row_id, model.status.in_(list(statuses)))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        await session.rollback()
        return False
    await session.commit()
    return True


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def progress_stats(
    completed: int, total: int, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """The progress block a running job stores in ``summary_stats``: how far
    it is, and when it last said so (its heartbeat)."""
    return {
        "progress": {
            "completed": completed,
            "total": total,
            "at": (now or utcnow()).isoformat(),
        }
    }


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def last_activity(
    summary_stats: Optional[Dict[str, Any]],
    started_at: Optional[datetime],
    created_at: Optional[datetime],
) -> Optional[datetime]:
    """When the job last showed life: its latest progress stamp, else when it
    started, else when it was created."""
    stamp = ((summary_stats or {}).get("progress") or {}).get("at")
    if stamp:
        try:
            return _aware(datetime.fromisoformat(str(stamp)))
        except ValueError:
            pass
    return _aware(started_at) or _aware(created_at)


def is_stale(
    summary_stats: Optional[Dict[str, Any]],
    started_at: Optional[datetime],
    created_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    """True when the job has shown no progress for ``STALE_AFTER``."""
    seen = last_activity(summary_stats, started_at, created_at)
    if seen is None:
        return True
    return (now or utcnow()) - seen >= STALE_AFTER


def orphan_message(
    summary_stats: Optional[Dict[str, Any]],
    started_at: Optional[datetime],
    created_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> str:
    """The error text stored on a job failed for showing no progress."""
    seen = last_activity(summary_stats, started_at, created_at)
    if seen is None:
        return "no progress recorded: the api copy running it stopped (orphaned task)"
    minutes = int(((now or utcnow()) - seen).total_seconds() // 60)
    return (
        f"no progress for {minutes} min: "
        "the api copy running it stopped (orphaned task)"
    )


__all__ = [
    "STALE_AFTER",
    "is_stale",
    "last_activity",
    "orphan_message",
    "progress_stats",
    "utcnow",
    "write_while",
]
