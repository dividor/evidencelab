"""Add sys_parsed_folder and sys_ocr_applied columns to docs tables.

The OCR fallback feature needs sys_parsed_folder to locate and delete
stale parsed output, and sys_ocr_applied to track which documents
were processed with OCR.

Revision ID: 0020_add_ocr_columns
Revises: 0019_create_api_keys_table
Create Date: 2026-03-27
"""

from sqlalchemy import text

from alembic import op  # type: ignore[attr-defined]

revision = "0020_add_ocr_columns"
down_revision = "0019_create_api_keys_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename LIKE 'docs_%'"
        )
    )
    tables = [row[0] for row in rows]

    for table in tables:
        # Add sys_parsed_folder if not exists
        conn.execute(
            text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                f"sys_parsed_folder TEXT"
            )
        )
        # Add sys_ocr_applied if not exists
        conn.execute(
            text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                f"sys_ocr_applied BOOLEAN DEFAULT FALSE"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename LIKE 'docs_%'"
        )
    )
    tables = [row[0] for row in rows]

    for table in tables:
        conn.execute(
            text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS sys_parsed_folder")
        )
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS sys_ocr_applied"))
