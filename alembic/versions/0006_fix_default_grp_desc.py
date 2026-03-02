"""Fix default group description (shortened revision ID for varchar(32) compat).

Revision ID: 0006_fix_default_grp_desc
Revises: 0005_add_lockout_and_audit
Create Date: 2026-03-01 18:00:00
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0006_fix_default_grp_desc"
down_revision = "0005_add_lockout_and_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_groups
        SET description = 'Default Group'
        WHERE name = 'Default'
          AND description = 'Default group — access to all data sources'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE user_groups
        SET description = 'Default group — access to all data sources'
        WHERE name = 'Default'
          AND description = 'Default Group'
        """
    )
