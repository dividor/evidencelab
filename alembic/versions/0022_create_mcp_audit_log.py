"""Create mcp_audit_log table for MCP tool call auditing.

Revision ID: 0022_create_mcp_audit_log
Revises: 0021_tune_autovacuum_tables
Create Date: 2026-03-27
"""

from sqlalchemy import text

from alembic import op  # type: ignore[attr-defined]

revision = "0022_create_mcp_audit_log"
down_revision = "0021_tune_autovacuum_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS mcp_audit_log (
            id              BIGSERIAL PRIMARY KEY,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            tool_name       TEXT        NOT NULL,
            auth_type       TEXT        NOT NULL,
            user_id         TEXT,
            key_hash        TEXT,
            client_ip       TEXT,
            input_params    JSONB,
            output_summary  TEXT,
            duration_ms     DOUBLE PRECISION,
            status          TEXT        NOT NULL DEFAULT 'ok',
            error_message   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_mcp_audit_log_created_at
            ON mcp_audit_log (created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_mcp_audit_log_tool_name
            ON mcp_audit_log (tool_name);

        CREATE INDEX IF NOT EXISTS idx_mcp_audit_log_user_id
            ON mcp_audit_log (user_id)
            WHERE user_id IS NOT NULL;
        """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS mcp_audit_log;"))
