"""Add account lockout columns and audit log table.

Revision ID: 0005_add_lockout_and_audit
Revises: 0004_create_user_tables
Create Date: 2026-03-01 12:00:00
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0005_add_lockout_and_audit"
down_revision = "0004_create_user_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Account lockout columns on the users table
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ
        """
    )

    # Audit log — immutable, append-only table for security events
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            event_type VARCHAR(50) NOT NULL,
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            user_email VARCHAR(320),
            ip_address VARCHAR(45),
            details JSONB
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_timestamp " "ON audit_log(timestamp)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_user_id " "ON audit_log(user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_event_type " "ON audit_log(event_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS locked_until")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS failed_login_attempts")
