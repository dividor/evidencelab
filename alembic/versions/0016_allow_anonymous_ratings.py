"""Allow anonymous ratings.

Make user_id nullable on user_ratings so non-logged-in visitors
can submit ratings.

Revision ID: 0016_allow_anonymous_ratings
Revises: 0015_create_conversation_tables
Create Date: 2026-03-11
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0016_allow_anonymous_ratings"
down_revision = "0015_create_conversation_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("user_ratings", "user_id", nullable=True)
    # Change FK ondelete from CASCADE to SET NULL so deleting a user
    # preserves anonymous-like ratings rather than removing them.
    op.drop_constraint("user_ratings_user_id_fkey", "user_ratings", type_="foreignkey")
    op.create_foreign_key(
        "user_ratings_user_id_fkey",
        "user_ratings",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Remove anonymous ratings before making column non-nullable
    op.execute("DELETE FROM user_ratings WHERE user_id IS NULL")
    op.drop_constraint("user_ratings_user_id_fkey", "user_ratings", type_="foreignkey")
    op.create_foreign_key(
        "user_ratings_user_id_fkey",
        "user_ratings",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("user_ratings", "user_id", nullable=False)
