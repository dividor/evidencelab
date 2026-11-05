"""Identify anonymous raters by browser.

Anonymous ratings had no owner, so every click stored a new row and a visitor
could never see or change their own rating. ``user_ratings.anonymous_id`` holds
the random ID the API gives each anonymous browser in an httpOnly cookie, so a
browser keeps one rating per item, as a signed-in user does.

Revision ID: 0038_add_rating_anonymous_id
Revises: 0037_merge_heads_1_6_4
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0038_add_rating_anonymous_id"
down_revision = "0037_merge_heads_1_6_4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ratings",
        sa.Column("anonymous_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_user_ratings_anonymous_id", "user_ratings", ["anonymous_id"])


def downgrade() -> None:
    op.drop_index("ix_user_ratings_anonymous_id", table_name="user_ratings")
    op.drop_column("user_ratings", "anonymous_id")
