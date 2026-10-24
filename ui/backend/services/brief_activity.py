"""The Activity log's "brief" row, written from the stored renumbered brief.

One ``user_activity`` row per brief, keyed by the brief's stable
``activityId`` and owner-scoped exactly like ``routes/activity.py``'s upsert.
Its text is the renumbered markdown readers see and its sources are the
References list in display order, so the admin Activity view, the screen and
the citation check carry the same numbers. Token usage on the same row is
recorded separately (``usage_recorder``) and never touched here.
"""

import copy
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ui.backend.auth.models import UserActivity
from ui.backend.services import brief_citations as bc

logger = logging.getLogger(__name__)

ACTIVITY_TYPE_BRIEF = "brief"


def brief_markdown(content: Dict[str, Any]) -> str:
    """Every section as a heading plus its renumbered text."""
    parts = []
    for section in content.get("sections") or []:
        text = (section.get("renumbered") or {}).get("content") or ""
        body = f"\n\n{text}" if text else ""
        parts.append(f"## {section.get('title', '')}{body}")
    return "\n\n".join(parts)


def brief_search_results(content: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The References list as activity ``search_results`` rows, in display order."""
    sources = {src["id"]: src for src in content.get("sources") or []}
    rows = []
    for ref in content.get("references") or []:
        source = sources.get(ref["sourceId"], {})
        rows.append(
            {
                "n": ref["n"],
                "chunk_id": source.get("chunkId") or "",
                "doc_id": source.get("docId") or "",
                "title": source.get("title") or "",
                "score": source.get("score") or 0,
                "page_num": ref.get("page"),
                "chunk_text": source.get("text") or "",
                "link": source.get("pdfUrl") or source.get("reportUrl") or "",
            }
        )
    return rows


def _activity_uuid(content: Dict[str, Any]) -> Optional[uuid.UUID]:
    raw = content.get("activityId")
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        logger.warning(
            "Brief activityId %r is not a UUID; no activity row written", raw
        )
        return None


async def _find_row(
    session: Any,
    search_uuid: uuid.UUID,
    user_id: Optional[uuid.UUID],
    session_id: Optional[str],
) -> Optional[UserActivity]:
    stmt = select(UserActivity).where(UserActivity.search_id == search_uuid)
    if user_id is not None:
        stmt = stmt.where(UserActivity.user_id == user_id)
    else:
        stmt = stmt.where(UserActivity.session_id == session_id)
    return (await session.execute(stmt)).scalars().first()


def activity_row_values(
    content: Dict[str, Any],
    title: str,
    brief_id: Optional[uuid.UUID],
    existing_filters: Any,
) -> Dict[str, Any]:
    """The columns a brief's activity row takes from its stored content: the
    renumbered text, the References as results, and the ``brief`` type. Used
    by the live upsert below and by the conversion script and data migration,
    which write rows without the ORM."""
    filters = copy.deepcopy(existing_filters or {})
    filters["type"] = ACTIVITY_TYPE_BRIEF
    if brief_id is not None:
        filters["brief_id"] = str(brief_id)
    return {
        "query": title,
        "filters": filters,
        "search_results": brief_search_results(content),
        "ai_summary": brief_markdown(content),
    }


async def upsert_brief_activity(
    session: Any,
    *,
    content: Dict[str, Any],
    title: str,
    brief_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    session_id: Optional[str] = None,
) -> Optional[UserActivity]:
    """Write the brief's activity row from ``content`` (format 2, renumbered).

    Adds the row to ``session`` without committing, so it lands in the same
    transaction as the brief save. Returns the row, or None when the brief
    has no usable activity id or no owner context.
    """
    search_uuid = _activity_uuid(content)
    if search_uuid is None or (user_id is None and not session_id):
        return None
    row: Any = await _find_row(session, search_uuid, user_id, session_id)
    if row is None:
        row = UserActivity(
            user_id=user_id,
            session_id=session_id if user_id is None else None,
            search_id=search_uuid,
            query=title,
        )
        session.add(row)
    for key, value in activity_row_values(
        content, title, brief_id, row.filters
    ).items():
        setattr(row, key, value)
    return row


__all__ = [
    "activity_row_values",
    "brief_markdown",
    "brief_search_results",
    "upsert_brief_activity",
]


# Re-exported for callers that only need the format check.
require_current_format = bc.require_current_format
