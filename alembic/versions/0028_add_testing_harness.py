"""Create the admin evaluation harness tables.

Adds four tables for the superuser-only Search & AI-Summary testing harness:

- ``test_datasets``    — reusable named sets of test cases per capability.
- ``test_cases``       — input + expectation assertions for one case.
- ``test_experiments`` — one run of a dataset against the live capability.
- ``test_results``     — per-case outcome (status, score, raw output, asserts).

Revision ID: 0028_add_testing_harness
Revises: 0027_merge_0026_heads
Create Date: 2026-06-14

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0028_add_testing_harness"
down_revision = "0027_merge_0026_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_datasets",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("data_source", sa.String(255), nullable=False),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "test_cases",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("test_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("input", JSONB, nullable=False),
        sa.Column(
            "expectations",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_test_cases_dataset_id", "test_cases", ["dataset_id"])

    op.create_table(
        "test_experiments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("test_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("config", JSONB, nullable=True),
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
    op.create_index(
        "ix_test_experiments_dataset_id", "test_experiments", ["dataset_id"]
    )

    op.create_table(
        "test_results",
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
        sa.Column(
            "test_case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("actual_output", JSONB, nullable=True),
        sa.Column("assertion_results", JSONB, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_test_results_experiment_id", "test_results", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_test_results_experiment_id", table_name="test_results")
    op.drop_table("test_results")
    op.drop_index("ix_test_experiments_dataset_id", table_name="test_experiments")
    op.drop_table("test_experiments")
    op.drop_index("ix_test_cases_dataset_id", table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_table("test_datasets")
