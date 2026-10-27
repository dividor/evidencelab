"""Add brief_citation_checks and brief_citation_check_passages.

The Evaluation Harness "Brief" check judges every cited passage of a saved
brief against the stored source excerpts it cites (an LLM judge plus a
mechanical quote check). One row per check holds its status, judge model and
summary; one row per judged passage holds the verdict and everything a
reviewer needs to assess it, so the UI can filter and the Excel export can be
rebuilt at any time.

Revision ID: 0034_add_brief_citation_checks
Revises: 0033_rename_trace_url
Create Date: 2026-09-24

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0034_add_brief_citation_checks"
down_revision = "0033_rename_trace_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brief_citation_checks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "brief_id",
            UUID(as_uuid=True),
            sa.ForeignKey("briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brief_title", sa.String(500), nullable=False),
        sa.Column("data_source", sa.String(255), nullable=True),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("judge_model", sa.String(255), nullable=True),
        sa.Column("model_combo", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary_stats", JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_brief_citation_checks_brief_id", "brief_citation_checks", ["brief_id"]
    )
    op.create_table(
        "brief_citation_check_passages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "check_id",
            UUID(as_uuid=True),
            sa.ForeignKey("brief_citation_checks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("passage_id", sa.Integer(), nullable=False),
        sa.Column("brief_section", sa.Text(), nullable=False),
        sa.Column("passage", sa.Text(), nullable=False),
        sa.Column("citations", sa.String(255), nullable=False),
        sa.Column("documents", sa.Text(), nullable=False),
        sa.Column("sources", JSONB(), nullable=False),
        sa.Column("dangling_citations", sa.String(255), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("problems", JSONB(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("supporting_quotes", JSONB(), nullable=False),
        sa.Column("quotes_verified", sa.String(32), nullable=False),
        sa.Column("quote_not_in_source", sa.Boolean(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_brief_citation_check_passages_check_id",
        "brief_citation_check_passages",
        ["check_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_brief_citation_check_passages_check_id",
        table_name="brief_citation_check_passages",
    )
    op.drop_table("brief_citation_check_passages")
    op.drop_index(
        "ix_brief_citation_checks_brief_id", table_name="brief_citation_checks"
    )
    op.drop_table("brief_citation_checks")
