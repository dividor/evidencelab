"""Add password_history column for ASVS V2.1.10 password reuse prevention.

Revision ID: 0016_add_password_history
Revises: 0015_create_conversation_tables
Create Date: 2026-03-10
"""

from alembic import op  # type: ignore

# revision identifiers, used by Alembic.
revision = "0016_add_password_history"
down_revision = "0015_create_conversation_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS password_history JSONB
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_history")
