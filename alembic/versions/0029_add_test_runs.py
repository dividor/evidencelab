"""Add test_runs so an experiment can be run many times.

Introduces a first-class ``test_runs`` table (one row per execution of an
experiment) and links ``test_results`` to a run via a new nullable ``run_id``.
Existing pre-runs result rows keep ``run_id = NULL``.

Revision ID: 0029_add_test_runs
Revises: 0028_add_testing_harness
Create Date: 2026-06-14

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0029_add_test_runs"
down_revision = "0028_add_testing_harness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_runs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "experiment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("test_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_number", sa.Integer, nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("summary_stats", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_test_runs_experiment_id", "test_runs", ["experiment_id"])

    op.add_column(
        "test_results",
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("test_runs.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_test_results_run_id", "test_results", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_test_results_run_id", table_name="test_results")
    op.drop_column("test_results", "run_id")
    op.drop_index("ix_test_runs_experiment_id", table_name="test_runs")
    op.drop_table("test_runs")
