"""Add sys_status columns to docs tables.

Revision ID: 0002_add_sys_status_columns
Revises: 0001_create_sidecar_tables
Create Date: 2026-01-28 00:00:00
"""

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

revision = "0002_add_sys_status_columns"
down_revision = "0001_create_sidecar_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("docs_uneg", sa.Column("sys_status", sa.Text(), nullable=True))
    op.add_column(
        "docs_uneg",
        sa.Column("sys_status_timestamp", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("docs_uneg", "sys_status_timestamp")
    op.drop_column("docs_uneg", "sys_status")
