"""Tie a brief citation check to the brief version it judged.

A check starts by pinning the brief's current version (``brief_versions``;
a brief with no version yet gets its baseline version first), so the check
and the version Log name the same thing, the Fact Checker can tell section
by section whether the brief still reads as it did when it was judged, and
a version a check judged is never merged into by later typing saves.
Existing checks keep NULL: they predate the link.

Revision ID: 0040_add_brief_check_version
Revises: 0039_add_brief_versions
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0040_add_brief_check_version"
down_revision = "0039_add_brief_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "brief_citation_checks",
        sa.Column(
            "brief_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("brief_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "brief_citation_checks",
        sa.Column("brief_version_number", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_brief_citation_checks_brief_version_id",
        "brief_citation_checks",
        ["brief_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_brief_citation_checks_brief_version_id",
        table_name="brief_citation_checks",
    )
    op.drop_column("brief_citation_checks", "brief_version_number")
    op.drop_column("brief_citation_checks", "brief_version_id")
