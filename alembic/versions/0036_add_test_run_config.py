"""Record the resolved configuration of each evaluation run.

A run's models and settings were only derivable from the experiment at the time
it ran; once the experiment, its group or the model combos changed, runs were
no longer comparable. ``test_runs.config`` keeps the snapshot the harness
actually ran with (models, group, search and summary settings).

Revision ID: 0036_add_test_run_config
Revises: 0035_share_templates_voices
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0036_add_test_run_config"
down_revision = "0035_share_templates_voices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_runs",
        sa.Column("config", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("test_runs", "config")
