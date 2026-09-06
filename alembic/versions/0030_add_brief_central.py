"""Add Brief Central tables: briefs, brief_templates, voice_profiles, brief_shares.

Briefs move from browser localStorage to server-side storage so they can be
shared (viewer-only) with other users and groups. Templates save a heading
structure for reuse; voice profiles hold style instructions applied when
sections are written.

Revision ID: 0030_add_brief_central
Revises: 0029_add_test_runs
Create Date: 2026-08-09

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0030_add_brief_central"
down_revision = "0029_add_test_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_profiles",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("instructions", sa.Text, nullable=False),
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
    op.create_index("ix_voice_profiles_user_id", "voice_profiles", ["user_id"])

    op.create_table(
        "brief_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("headings", JSONB, nullable=False),
        sa.Column(
            "with_text", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column("use_count", sa.Integer, nullable=False, server_default="0"),
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
    op.create_index("ix_brief_templates_user_id", "brief_templates", ["user_id"])

    op.create_table(
        "briefs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("query", sa.Text, nullable=True),
        sa.Column("data_source", sa.String(255), nullable=True),
        sa.Column(
            "voice_profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("voice_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content", JSONB, nullable=False),
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
    op.create_index("ix_briefs_user_id", "briefs", ["user_id"])

    op.create_table(
        "brief_shares",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "brief_id",
            UUID(as_uuid=True),
            sa.ForeignKey("briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shared_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(shared_user_id IS NOT NULL) OR (group_id IS NOT NULL)",
            name="ck_brief_shares_target",
        ),
        sa.UniqueConstraint("brief_id", "shared_user_id", name="uq_brief_shares_user"),
        sa.UniqueConstraint("brief_id", "group_id", name="uq_brief_shares_group"),
    )
    op.create_index("ix_brief_shares_brief_id", "brief_shares", ["brief_id"])
    op.create_index(
        "ix_brief_shares_shared_user_id", "brief_shares", ["shared_user_id"]
    )
    op.create_index("ix_brief_shares_group_id", "brief_shares", ["group_id"])


def downgrade() -> None:
    op.drop_table("brief_shares")
    op.drop_table("briefs")
    op.drop_table("brief_templates")
    op.drop_table("voice_profiles")
