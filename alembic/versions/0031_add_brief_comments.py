"""Add brief_comments: threaded comments anchored to passages of a brief.

Recipients of a shared brief highlight text and leave a comment; the author
and other recipients reply in a thread, and comments can be edited by their
author or marked resolved.

Anchors keep the quoted text (with a little context either side) rather than
character offsets, so a comment can still be located after the section it
belongs to is re-researched and the prose re-flows.

Revision ID: 0031_add_brief_comments
Revises: 0030_add_brief_central
Create Date: 2026-08-12

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0031_add_brief_comments"
down_revision = "0030_add_brief_central"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brief_comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "brief_id",
            UUID(as_uuid=True),
            sa.ForeignKey("briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Replies point at the comment that opened the thread (one level deep).
        sa.Column(
            "parent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("brief_comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("section_id", sa.String(64), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("quote_prefix", sa.Text(), nullable=True),
        sa.Column("quote_suffix", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "resolved_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
    # Listing a brief's comments and expanding a thread are the two hot paths.
    op.create_index(
        "ix_brief_comments_brief_id", "brief_comments", ["brief_id"], unique=False
    )
    op.create_index(
        "ix_brief_comments_parent_id", "brief_comments", ["parent_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_brief_comments_parent_id", table_name="brief_comments")
    op.drop_index("ix_brief_comments_brief_id", table_name="brief_comments")
    op.drop_table("brief_comments")
