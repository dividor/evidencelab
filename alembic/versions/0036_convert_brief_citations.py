"""Convert stored briefs to citation format 2.

Before format 2 a brief kept each section's research output with the
agent's own per-section ``[n]`` numbers and renumbered only in the browser,
so the stored brief, the Activity log and the citation check disagreed with
the screen. Format 2 stores, for every section, the agent's original output
as a run, a brief-wide source list keyed by chunk id, and the renumbered
version the API computes (``ui/backend/services/brief_citations.py``).

This data migration converts every brief still in the old shape through the
same converter the reviewed CLI uses
(``scripts/fixes/convert_brief_citations.py``, which also produces the
dry-run report and file backups), one brief per statement. Downgrade rebuilds
the old shape from each section's current run.

Revision ID: 0036_convert_brief_citations
Revises: 0035_share_templates_voices
Create Date: 2026-10-19

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``). It
revises 0035, the head of rc/v1.6.4 when it was written; a branch merged
after it that also revises 0035 needs a merge revision (as 0027 did).
"""

import json
from typing import Any, Dict

import sqlalchemy as sa

from alembic import op

revision = "0036_convert_brief_citations"
down_revision = "0035_share_templates_voices"
branch_labels = None
depends_on = None


def _rows(conn: Any) -> list:
    return conn.execute(
        sa.text("SELECT id, user_id, title, content FROM briefs")
    ).fetchall()


def _write(conn: Any, brief_id: Any, content: Dict[str, Any]) -> None:
    conn.execute(
        sa.text("UPDATE briefs SET content = CAST(:content AS jsonb) WHERE id = :id"),
        {"content": json.dumps(content), "id": brief_id},
    )


def upgrade() -> None:
    from ui.backend.services.brief_citations_convert import (
        convert_legacy,
        is_legacy,
        refresh_activity_row,
    )

    conn = op.get_bind()
    for brief_id, user_id, title, content in _rows(conn):
        if isinstance(content, str):
            content = json.loads(content)
        if not is_legacy(content or {}):
            continue
        converted, _report = convert_legacy(content or {})
        _write(conn, brief_id, converted)
        # The brief's Activity row now carries the renumbered text and
        # References, as the API writes it on every save.
        refresh_activity_row(conn, brief_id, user_id, title, converted)


def _to_legacy(content: Dict[str, Any]) -> Dict[str, Any]:
    """The pre-format-2 shape: each section's current run as its content and
    sources (earlier runs, the source list and the renumbering are dropped)."""
    from ui.backend.services.brief_citation_model import current_run

    legacy = {
        key: value
        for key, value in content.items()
        if key
        not in (
            "citationsVersion",
            "sources",
            "references",
            "referenceGroups",
            "referenceGrouping",
            "renumberedAt",
            "sections",
        )
    }
    sections = []
    for section in content.get("sections") or []:
        run = current_run(section)
        row = {
            key: value
            for key, value in section.items()
            if key not in ("runs", "currentRunId", "renumbered")
        }
        row["status"] = "done" if run else "pending"
        row["content"] = run["content"] if run else ""
        row["sources"] = run["sources"] if run else []
        sections.append(row)
    legacy["sections"] = sections
    legacy["sourceCount"] = sum(len(s["sources"]) for s in sections)
    return legacy


def downgrade() -> None:
    conn = op.get_bind()
    for brief_id, _user_id, _title, content in _rows(conn):
        if isinstance(content, str):
            content = json.loads(content)
        if (content or {}).get("citationsVersion") != 2:
            continue
        _write(conn, brief_id, _to_legacy(content))
