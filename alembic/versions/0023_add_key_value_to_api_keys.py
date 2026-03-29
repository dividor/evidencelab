"""Add key_value column to api_keys for admin copy support.

Revision ID: 0023_add_key_value_to_api_keys
Revises: 2a4d7830d56f
Create Date: 2026-03-29
"""

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

revision = "0023_add_key_value_to_api_keys"  # pragma: allowlist secret
down_revision = "0022_create_mcp_audit_log"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("key_value", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "key_value")
