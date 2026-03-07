"""Add map_abstract and map_topic columns to all docs tables.

These columns are driven by config.json field_mapping entries.
Future map columns are auto-created at runtime by ensure_map_doc_columns().

Revision ID: 0013_add_map_abstract_topic
Revises: 0012_create_saved_research
Create Date: 2026-03-07
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0013_add_map_abstract_topic"
down_revision = "0012_create_saved_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename LIKE 'docs_%'"
    ).fetchall()
    for (table_name,) in rows:
        op.execute(
            f"ALTER TABLE {table_name} " f"ADD COLUMN IF NOT EXISTS map_abstract TEXT"
        )
        op.execute(
            f"ALTER TABLE {table_name} " f"ADD COLUMN IF NOT EXISTS map_topic TEXT"
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename LIKE 'docs_%'"
    ).fetchall()
    for (table_name,) in rows:
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS map_abstract")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS map_topic")
