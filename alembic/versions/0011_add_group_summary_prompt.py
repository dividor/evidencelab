"""Add summary_prompt column to user_groups.

Revision ID: 0011_add_group_summary_prompt
Revises: 0010_split_display_name
Create Date: 2026-03-05 22:00:00
"""

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

revision = "0011_add_group_summary_prompt"
down_revision = "0010_split_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_groups", sa.Column("summary_prompt", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("user_groups", "summary_prompt")
