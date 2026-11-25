"""Keep a running AI cost per UTC day for the daily AI limit.

``AI_DAILY_COST_LIMIT_USD`` pauses the site's AI features once a day's AI
cost reaches it. The recorder adds each call's cost to that day's row as it
records the usage, so the check reads one row instead of summing
``user_activity``, whose rows also collect usage from later days.

Revision ID: 0041_add_ai_daily_spend
Revises: 0040_add_brief_check_version
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0041_add_ai_daily_spend"
down_revision = "0040_add_brief_check_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_daily_spend",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("day", name="uq_ai_daily_spend_day"),
    )


def downgrade() -> None:
    op.drop_table("ai_daily_spend")
