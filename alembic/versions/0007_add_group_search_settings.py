"""Add search_settings JSONB column to user_groups.

Revision ID: 0007_add_group_search_settings
Revises: 0006_fix_default_group_description
Create Date: 2026-03-01 20:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op  # type: ignore[attr-defined]

revision = "0007_add_group_search_settings"
down_revision = "0006_fix_default_group_description"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_groups", sa.Column("search_settings", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("user_groups", "search_settings")
