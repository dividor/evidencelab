"""Add user ratings and activity tables.

Revision ID: 0008_add_ratings_activity
Revises: 0007_add_group_search_settings
Create Date: 2026-03-02 17:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op  # type: ignore[attr-defined]

revision = "0008_add_ratings_activity"
down_revision = "0007_add_group_search_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # User ratings (search results, AI summaries, doc summaries, taxonomy tags)
    op.create_table(
        "user_ratings",
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
        sa.Column("rating_type", sa.String(50), nullable=False),
        sa.Column("reference_id", sa.String(255), nullable=False),
        sa.Column("item_id", sa.String(255), nullable=True),
        sa.Column("score", sa.SmallInteger, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("context", JSONB, nullable=True),
        sa.Column("url", sa.Text, nullable=True),
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
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_user_ratings_score"),
    )
    op.create_index("ix_user_ratings_user_id", "user_ratings", ["user_id"])
    op.create_index("ix_user_ratings_type", "user_ratings", ["rating_type"])
    op.create_index("ix_user_ratings_reference_id", "user_ratings", ["reference_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_user_ratings_unique "
        "ON user_ratings(user_id, rating_type, reference_id, COALESCE(item_id, ''))"
    )

    # User activity (automatic search activity logging)
    op.create_table(
        "user_activity",
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
        sa.Column("search_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("filters", JSONB, nullable=True),
        sa.Column("search_results", JSONB, nullable=True),
        sa.Column("ai_summary", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column(
            "has_ratings", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_user_activity_user_id", "user_activity", ["user_id"])
    op.create_index("ix_user_activity_search_id", "user_activity", ["search_id"])
    op.create_index(
        "ix_user_activity_created_at",
        "user_activity",
        ["created_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_table("user_activity")
    op.drop_table("user_ratings")
