"""Split display_name into first_name and last_name.

Revision ID: 0010_split_display_name
Revises: 0009_add_langsmith_trace_url
Create Date: 2026-03-04 00:00:00
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0010_split_display_name"
down_revision = "0009_add_langsmith_trace_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(255)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR(255)")

    # Migrate existing data: split display_name on first space
    op.execute(
        """
        UPDATE users
        SET first_name = split_part(display_name, ' ', 1),
            last_name  = CASE
                WHEN position(' ' IN display_name) > 0
                THEN substring(display_name FROM position(' ' IN display_name) + 1)
                ELSE NULL
            END
        WHERE display_name IS NOT NULL
        """
    )

    # Drop the old column
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS display_name")


def downgrade() -> None:
    # Re-add display_name
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(255)")

    # Merge first_name + last_name back into display_name
    op.execute(
        """
        UPDATE users
        SET display_name = TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, ''))
        WHERE first_name IS NOT NULL OR last_name IS NOT NULL
        """
    )
    op.execute("UPDATE users SET display_name = NULL WHERE display_name = ''")

    # Drop the new columns
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS first_name")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_name")
