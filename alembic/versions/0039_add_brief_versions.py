"""Add brief_versions: every change to a signed-in brief as a version.

The API writes a row in the same transaction as every change to a brief
(each save, research run, reject and restore), so the brief's version Log and
"Restore whole brief to this version" read from the database, never the
browser. Existing briefs get their first version (the brief as it was) the
next time they change.

Revision ID: 0039_add_brief_versions
Revises: 0038_add_rating_anonymous_id
Create Date: 2026-11-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0039_add_brief_versions"
down_revision = "0038_add_rating_anonymous_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brief_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "brief_id",
            UUID(as_uuid=True),
            sa.ForeignKey("briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("section_id", sa.String(64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("brief_id", "number", name="uq_brief_versions_number"),
    )
    op.create_index("ix_brief_versions_brief_id", "brief_versions", ["brief_id"])


def downgrade() -> None:
    op.drop_index("ix_brief_versions_brief_id", table_name="brief_versions")
    op.drop_table("brief_versions")
