"""Add sys_status columns to docs tables.

Revision ID: 0002_add_sys_status_columns
Revises: 0001_create_sidecar_tables
Create Date: 2026-01-28 00:00:00
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0002_add_sys_status_columns"
down_revision = "0001_create_sidecar_tables"
branch_labels = None
depends_on = None


def _add_column_if_not_exists(table: str, column: str, col_type: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = '{table}'
                  AND column_name = '{column}'
            ) THEN
                ALTER TABLE {table} ADD COLUMN {column} {col_type};
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _add_column_if_not_exists("docs_uneg", "sys_status", "TEXT")
    _add_column_if_not_exists("docs_uneg", "sys_status_timestamp", "TIMESTAMPTZ")


def downgrade() -> None:
    op.drop_column("docs_uneg", "sys_status_timestamp")
    op.drop_column("docs_uneg", "sys_status")
