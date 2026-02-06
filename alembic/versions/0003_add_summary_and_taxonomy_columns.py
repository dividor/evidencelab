"""Add sys_full_summary and sys_taxonomies columns to docs tables.

Revision ID: 0003_add_summary_and_taxonomy_columns
Revises: 0002_add_sys_status_columns
Create Date: 2026-02-06 00:00:00
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0003_add_summary_and_taxonomy_columns"
down_revision = "0002_add_sys_status_columns"
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
    _add_column_if_not_exists("docs_uneg", "sys_full_summary", "TEXT")
    _add_column_if_not_exists("docs_uneg", "sys_taxonomies", "JSONB")


def downgrade() -> None:
    op.drop_column("docs_uneg", "sys_taxonomies")
    op.drop_column("docs_uneg", "sys_full_summary")
