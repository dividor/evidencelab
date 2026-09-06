"""Add token-usage and cost columns to test_results.

The evaluation harness makes real LLM calls (AI-summary generation plus one
LLM-judge call per distinct rubric per case) whose token usage was previously
invisible. Each evaluated case now persists its combined usage:

- ``prompt_tokens``     : input tokens across the case's summary + judge calls.
- ``completion_tokens`` : output tokens across the case's summary + judge calls.
- ``cost_usd``          : cost summed per call from each call's own model rate
  (6 decimals so sub-cent values stay visible; NULL when no rate is known).

Run-level totals are aggregated into ``test_runs.summary_stats`` (JSONB, no
schema change) and mirrored into a per-run ``user_activity`` row so the admin
Token Usage rollup includes evaluation spend.

All columns are nullable with no defaults — historical rows render as "—"
and no backfill is needed.

Revision ID: 0032_add_eval_token_usage
Revises: 0031_add_brief_comments
Create Date: 2026-08-26

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``).
"""

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

revision = "0032_add_eval_token_usage"
down_revision = "0031_add_brief_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_results",
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "test_results",
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "test_results",
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("test_results", "cost_usd")
    op.drop_column("test_results", "completion_tokens")
    op.drop_column("test_results", "prompt_tokens")
