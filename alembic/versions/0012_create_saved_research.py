"""Create saved_research table.

Revision ID: 0012_create_saved_research
Revises: 0011_add_group_summary_prompt
Create Date: 2026-03-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op  # type: ignore[attr-defined]

revision = "0012_create_saved_research"
down_revision = "0011_add_group_summary_prompt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_research",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("filters", JSONB, nullable=True),
        sa.Column("data_source", sa.String(255), nullable=True),
        sa.Column("drilldown_tree", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_saved_research_user_id", "saved_research", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_research_user_id")
    op.drop_table("saved_research")
