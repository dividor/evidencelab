"""Add anonymous activity support.

Make user_id nullable and add session_id column to user_activity
so searches by non-logged-in visitors can be recorded.

Revision ID: 0014_add_anonymous_activity
Revises: 0013_add_map_abstract_topic
Create Date: 2026-03-07
"""

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

revision = "0014_add_anonymous_activity"
down_revision = "0013_add_map_abstract_topic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("user_activity", "user_id", nullable=True)
    op.add_column(
        "user_activity",
        sa.Column("session_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_user_activity_session_id", "user_activity", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_user_activity_session_id", table_name="user_activity")
    op.drop_column("user_activity", "session_id")
    op.execute("DELETE FROM user_activity WHERE user_id IS NULL")
    op.alter_column("user_activity", "user_id", nullable=False)
