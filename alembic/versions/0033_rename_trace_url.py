"""Rename user_activity.langsmith_trace_url to the vendor-neutral trace_url.

The column stores a link to the trace of the LLM call behind an activity
row. It was named after the one tracing backend the code supported; tracing
now goes through the project-owned ``utils.tracing`` port, which can be
backed by LangSmith, OpenTelemetry or nothing, so the column name should not
name a vendor. A rename keeps existing values.

The API emits both ``trace_url`` and the legacy ``langsmith_trace_url`` on
stream completion events for one release so older frontend bundles keep
working; the column itself changes now.

Revision ID: 0033_rename_trace_url
Revises: 0032_add_eval_token_usage
Create Date: 2026-09-17

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``).
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0033_rename_trace_url"
down_revision = "0032_add_eval_token_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("user_activity", "langsmith_trace_url", new_column_name="trace_url")


def downgrade() -> None:
    op.alter_column("user_activity", "trace_url", new_column_name="langsmith_trace_url")
