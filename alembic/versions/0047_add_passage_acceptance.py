"""Record a person's acceptance of a judged citation.

A reader of a brief can accept a passage the citation check judged (the Fact
Checker's "Accept citation"): the judge's verdict stays as it was, and the
passage row records who accepted it, when and with what comment, so the
document can show it as human approved and the Testing (Brief) table can
list it. The name is kept beside the user id so the table still names the
person after the account is deleted.

Revision ID: 0047_add_passage_acceptance
Revises: 0046_unwritten_brief_errors
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0047_add_passage_acceptance"
down_revision = "0046_unwritten_brief_errors"
branch_labels = None
depends_on = None

TABLE = "brief_citation_check_passages"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("human_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "human_accepted_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("human_accepted_by_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column("human_acceptance_comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(TABLE, "human_acceptance_comment")
    op.drop_column(TABLE, "human_accepted_by_name")
    op.drop_column(TABLE, "human_accepted_by_user_id")
    op.drop_column(TABLE, "human_accepted_at")
