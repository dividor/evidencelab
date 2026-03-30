"""Add protocol column to mcp_audit_log to distinguish MCP vs A2A calls.

Revision ID: 0024_mcp_audit_protocol
Revises: 0023_add_key_value_to_api_keys
Create Date: 2026-03-29
"""

from sqlalchemy import text

from alembic import op  # type: ignore[attr-defined]

revision = "0024_mcp_audit_protocol"
down_revision = "0023_add_key_value_to_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
        ALTER TABLE mcp_audit_log
            ADD COLUMN IF NOT EXISTS protocol TEXT NOT NULL DEFAULT 'mcp';

        CREATE INDEX IF NOT EXISTS idx_mcp_audit_log_protocol
            ON mcp_audit_log (protocol);
        """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
        DROP INDEX IF EXISTS idx_mcp_audit_log_protocol;
        ALTER TABLE mcp_audit_log DROP COLUMN IF EXISTS protocol;
        """
        )
    )
