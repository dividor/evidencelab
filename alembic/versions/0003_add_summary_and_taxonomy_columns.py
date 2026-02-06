"""Add sys_full_summary and sys_taxonomies columns to docs tables.

Revision ID: 0003_add_summary_and_taxonomy_columns
Revises: 0002_add_sys_status_columns
Create Date: 2026-02-06 00:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op  # type: ignore[attr-defined]

revision = "0003_add_summary_and_taxonomy_columns"
down_revision = "0002_add_sys_status_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("docs_uneg", sa.Column("sys_full_summary", sa.Text(), nullable=True))
    op.add_column(
        "docs_uneg", sa.Column("sys_taxonomies", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("docs_uneg", "sys_taxonomies")
    op.drop_column("docs_uneg", "sys_full_summary")
