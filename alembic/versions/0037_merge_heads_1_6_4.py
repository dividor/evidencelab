"""Merge the two migration heads that landed on rc/v1.6.4 in parallel.

``0036_add_test_run_config`` (PR #533) and ``0036_convert_brief_citations``
both revise ``0035_share_templates_voices``, so after both merged the branch
had two heads and ``alembic upgrade head`` refused to run, which stopped the
API container from starting. This empty merge revision joins them into one
head; neither revision ID is renamed, so databases that already applied either
one upgrade cleanly.

Revision ID: 0037_merge_heads_1_6_4
Revises: 0036_add_test_run_config, 0036_convert_brief_citations
Create Date: 2026-10-24
"""

revision = "0037_merge_heads_1_6_4"
down_revision = ("0036_add_test_run_config", "0036_convert_brief_citations")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to apply: this revision only joins the two heads."""


def downgrade() -> None:
    """Nothing to revert: this revision only joins the two heads."""
