"""Brief versions in the database: write one with every change to a brief,
list them, compare one with the version before it, restore a brief to one.

``record_version`` runs inside the transaction that saves the brief (see
``routes/brief_central.store_brief_content``), so a brief and its versions
never disagree. A save that changes nothing a reader would call a change
writes no version. Saves made while typing (headings, settings, a section's
text by hand) by the same person within ``application.brief.versions.
merge_minutes`` of the latest such version merge into it; research runs,
rejects and restores always start a new one. A brief saved before version
history began gets a first version holding it as it was, the first time it
changes.
"""

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ui.backend.auth.models import Brief, BriefVersion, User
from ui.backend.services import brief_versions as bv
from ui.backend.services.brief_citation_model import BriefCitationError

MERGE_SETTING = "application.brief.versions.merge_minutes"
MERGE_MINUTES_DEFAULT = 5


def merge_window() -> timedelta:
    """How long typing saves keep merging into the latest version (0 = never
    merge). Read from config.json; 5 minutes when the setting is left out."""
    from pipeline.db.config import get_application_config

    versions = (get_application_config().get("brief") or {}).get("versions") or {}
    minutes = versions.get("merge_minutes", MERGE_MINUTES_DEFAULT)
    if (
        isinstance(minutes, bool)
        or not isinstance(minutes, (int, float))
        or minutes < 0
    ):
        raise ValueError(f"{MERGE_SETTING} must be a number of minutes, 0 or more")
    return timedelta(minutes=minutes)


@dataclass(frozen=True)
class VersionChange:
    """What a route knows about the change it saves. ``kind`` None means a
    save from the browser (headings, settings, text by hand), described by
    comparing it with the latest version."""

    kind: Optional[str] = None
    section_id: Optional[str] = None
    detail: str = ""


class VersionError(BriefCitationError):
    """A version that cannot be read or restored as asked."""


def _section_title(snap: Dict[str, Any], section_id: Optional[str]) -> str:
    for section in snap.get("sections") or []:
        if section.get("id") == section_id:
            return section.get("title") or ""
    return ""


def _resolve(
    change: Optional[VersionChange],
    latest: Optional[BriefVersion],
    snap: Dict[str, Any],
) -> Tuple[str, Optional[str], str]:
    if change is None or change.kind is None:
        return bv.describe_change(latest.content if latest else None, snap)
    title = _section_title(snap, change.section_id)
    if not title and latest is not None:
        title = _section_title(latest.content, change.section_id)
    wording = change.kind
    if change.kind == "generate" and _had_text(latest, change.section_id):
        wording = "regenerate"
    return change.kind, change.section_id, bv.summarise(wording, title, change.detail)


def _had_text(latest: Optional[BriefVersion], section_id: Optional[str]) -> bool:
    """Whether the section had text in the latest version (a generate run on
    it is then a regeneration)."""
    for section in (latest.content if latest else {}).get("sections") or []:
        if section.get("id") == section_id:
            return bool(section.get("run"))
    return False


def _merges(
    latest: BriefVersion, kind: str, user_id, now: datetime, window: timedelta
) -> bool:
    return (
        window > timedelta(0)
        and kind in bv.TYPING_KINDS
        and latest.kind in bv.TYPING_KINDS
        and latest.created_by_id == user_id
        and now - latest.updated_at <= window
    )


async def latest_version(session: AsyncSession, brief_id) -> Optional[BriefVersion]:
    result = await session.execute(
        select(BriefVersion)
        .where(BriefVersion.brief_id == brief_id)
        .order_by(BriefVersion.number.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_version(
    session: AsyncSession, brief_id, number: int
) -> Optional[BriefVersion]:
    result = await session.execute(
        select(BriefVersion).where(
            BriefVersion.brief_id == brief_id, BriefVersion.number == number
        )
    )
    return result.scalars().first()


def _row(brief: Brief, number: int, user_id, kind, section_id, summary, snap, at):
    return BriefVersion(
        brief_id=brief.id,
        number=number,
        created_by_id=user_id,
        kind=kind,
        section_id=section_id,
        summary=summary,
        content=snap,
        created_at=at,
        updated_at=at,
    )


async def _merge_into(
    session: AsyncSession,
    brief: Brief,
    latest: BriefVersion,
    snap: Dict[str, Any],
    now: datetime,
) -> Optional[BriefVersion]:
    """Fold a typing save into the latest version, described against the
    version before it; a save that undoes the latest version removes it."""
    prior = await get_version(session, brief.id, latest.number - 1)
    prior_snap = prior.content if prior else None
    if prior_snap is not None and bv.signature(prior_snap) == bv.signature(snap):
        await session.delete(latest)
        return None
    kind, section_id, summary = bv.describe_change(prior_snap, snap)
    latest.kind, latest.section_id, latest.summary = kind, section_id, summary
    latest.content = snap
    latest.updated_at = now
    return latest


async def record_version(
    session: AsyncSession,
    brief: Brief,
    previous_content: Optional[Dict[str, Any]],
    user_id,
    change: Optional[VersionChange] = None,
    now: Optional[datetime] = None,
    previous_at: Optional[datetime] = None,
) -> Optional[BriefVersion]:
    """Write the version a change to ``brief`` (already holding the new
    content) makes; ``previous_content`` is the brief before the change
    (None for a new brief) and ``previous_at`` when it was last saved (read
    before the change: saving it moves ``brief.updated_at``). Returns the
    version written or updated."""
    now = now or datetime.now(timezone.utc)
    snap = await run_in_threadpool(bv.snapshot, brief.content)
    # One version writer per brief at a time: the next number is read here.
    await session.execute(
        select(Brief.id).where(Brief.id == brief.id).with_for_update()
    )
    latest = await latest_version(session, brief.id)
    if latest is None and previous_content is not None:
        baseline = await run_in_threadpool(bv.snapshot, previous_content)
        if bv.signature(baseline) == bv.signature(snap):
            # Nothing changed; the brief gets its first version when it does.
            return None
        latest = _row(
            brief,
            1,
            brief.user_id,
            bv.KIND_BASELINE,
            None,
            bv.summarise(bv.KIND_BASELINE),
            baseline,
            previous_at or now,
        )
        session.add(latest)
    if latest is not None and bv.signature(latest.content) == bv.signature(snap):
        # Only the browser's bookkeeping moved: the latest version keeps up.
        latest.content = snap
        return latest
    kind, section_id, summary = _resolve(change, latest, snap)
    if latest is not None and _merges(latest, kind, user_id, now, merge_window()):
        return await _merge_into(session, brief, latest, snap, now)
    row = _row(
        brief,
        latest.number + 1 if latest else 1,
        user_id,
        kind,
        section_id,
        summary,
        snap,
        now,
    )
    session.add(row)
    return row


async def _author_names(session: AsyncSession, ids) -> Dict[Any, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    result = await session.execute(select(User).where(User.id.in_(ids)))
    return {
        user.id: (user.full_name or user.email)
        for user in result.scalars().unique().all()
    }


async def count_versions(session: AsyncSession, brief_id) -> int:
    """How many versions a brief has, shown on its Document History link."""
    result = await session.execute(
        select(func.count())
        .select_from(BriefVersion)
        .where(BriefVersion.brief_id == brief_id)
    )
    return int(result.scalar_one())


async def list_versions(session: AsyncSession, brief_id) -> List[Dict[str, Any]]:
    """Every version of a brief, newest first, without their content."""
    result = await session.execute(
        select(
            BriefVersion.number,
            BriefVersion.kind,
            BriefVersion.section_id,
            BriefVersion.summary,
            BriefVersion.created_by_id,
            BriefVersion.created_at,
            BriefVersion.updated_at,
        )
        .where(BriefVersion.brief_id == brief_id)
        .order_by(BriefVersion.number.desc())
    )
    rows = result.all()
    names = await _author_names(session, [row.created_by_id for row in rows])
    latest = rows[0].number if rows else None
    return [
        {
            "number": row.number,
            "kind": row.kind,
            "section_id": row.section_id,
            "summary": row.summary,
            "author_name": names.get(row.created_by_id),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "is_current": row.number == latest,
        }
        for row in rows
    ]


async def _require(session: AsyncSession, brief: Brief, number: int) -> BriefVersion:
    row = await get_version(session, brief.id, number)
    if row is None:
        raise VersionError(f"Version {number} not found")
    return row


async def version_detail(
    session: AsyncSession, brief: Brief, number: int
) -> Dict[str, Any]:
    """One version, compared with the version before it, section by section."""
    row = await _require(session, brief, number)
    prior = await get_version(session, brief.id, number - 1)
    latest = await latest_version(session, brief.id)
    sources = (brief.content or {}).get("sources") or []

    def build() -> Dict[str, Any]:
        content = bv.materialise(row.content, sources)
        previous = bv.materialise(prior.content, sources) if prior else None
        return bv.compare(previous, content)

    changes = await run_in_threadpool(build)
    names = await _author_names(session, [row.created_by_id])
    return {
        "number": row.number,
        "kind": row.kind,
        "summary": row.summary,
        "author_name": names.get(row.created_by_id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "is_current": latest is not None and latest.number == row.number,
        "previous_number": prior.number if prior else None,
        "title": row.content.get("title") or brief.title,
        **changes,
    }


async def restored_content(
    session: AsyncSession, brief: Brief, number: int
) -> Dict[str, Any]:
    """The brief's content restored to a version (not yet saved)."""
    row = await _require(session, brief, number)
    latest = await latest_version(session, brief.id)
    if latest is not None and latest.number == number:
        raise VersionError("This is already the brief's current version")
    return await run_in_threadpool(
        bv.restore_brief, copy.deepcopy(brief.content or {}), row.content, number
    )
