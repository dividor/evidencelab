"""Tune autovacuum for large document and chunk tables.

Large tables (chunks_*) accumulate dead rows faster than autovacuum's
default 20% threshold can handle, causing bloat and write slowdowns.
This migration lowers the trigger thresholds and increases the cost
limit so autovacuum runs more often and does more work each cycle.

Revision ID: 0020_tune_autovacuum_tables
Revises: 0019_create_api_keys_table
Create Date: 2026-03-25
"""

from sqlalchemy import text

from alembic import op  # type: ignore[attr-defined]

revision = "0021_tune_autovacuum_tables"
down_revision = "0020_add_ocr_columns"
branch_labels = None
depends_on = None

# Tables that grow large and benefit from aggressive autovacuum.
# Pattern: chunks_* and docs_* per data source.
_LARGE_TABLE_PREFIXES = ("chunks_", "docs_")

# Autovacuum settings for large tables:
#   vacuum_scale_factor  0.02  = trigger at 2% dead rows (default 20%)
#   analyze_scale_factor 0.02  = re-analyze at 2% changes (default 10%)
#   vacuum_cost_limit    1000  = do more work per cycle  (default 200)
_SETTINGS = {
    "autovacuum_vacuum_scale_factor": "0.02",
    "autovacuum_analyze_scale_factor": "0.02",
    "autovacuum_vacuum_cost_limit": "1000",
}


def _get_matching_tables(conn) -> list[str]:
    """Return existing table names matching large-table prefixes."""
    result = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    tables = [row[0] for row in result]
    return [
        t
        for t in tables
        if any(t.startswith(prefix) for prefix in _LARGE_TABLE_PREFIXES)
    ]


def upgrade() -> None:
    conn = op.get_bind()
    tables = _get_matching_tables(conn)
    for table in tables:
        for param, value in _SETTINGS.items():
            op.execute(f"ALTER TABLE {table} SET ({param} = {value})")


def downgrade() -> None:
    conn = op.get_bind()
    tables = _get_matching_tables(conn)
    for table in tables:
        for param in _SETTINGS:
            op.execute(f"ALTER TABLE {table} RESET ({param})")
