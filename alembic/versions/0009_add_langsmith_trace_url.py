"""Add langsmith_trace_url column to user_activity.

Revision ID: 0009_add_langsmith_trace_url
Revises: 0008_add_ratings_activity
Create Date: 2026-03-02 18:00:00
"""

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

revision = "0009_add_langsmith_trace_url"
down_revision = "0008_add_ratings_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_activity",
        sa.Column("langsmith_trace_url", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_activity", "langsmith_trace_url")
