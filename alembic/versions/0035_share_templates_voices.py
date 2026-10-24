"""Share brief templates and voice profiles; templates keep prompts and defaults.

Templates and voice & tone profiles were private to their owner. They can now
be shared with a user or a group, the same way briefs are: recipients can use
them but not change them. Two share tables mirror ``brief_shares``.

Templates also keep the brief-level settings of the brief they came from: a
whole-brief prompt (the brief's research instructions), a default voice &
tone profile and a default section length. Per-heading prompts, voices and
length targets live in the existing ``headings`` JSON and need no schema
change.

Revision ID: 0035_share_templates_voices
Revises: 0034_add_brief_citation_checks
Create Date: 2026-09-29

Note: the revision ID is intentionally kept under 32 characters to fit the
stock ``alembic_version.version_num`` column type (``varchar(32)``).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0035_share_templates_voices"
down_revision = "0034_add_brief_citation_checks"
branch_labels = None
depends_on = None


def _create_share_table(table: str, item_column: str, item_table: str) -> None:
    """A share row grants one user or one group use of one item."""
    op.create_table(
        table,
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            item_column,
            UUID(as_uuid=True),
            sa.ForeignKey(f"{item_table}.id", ondelete="CASCADE"),
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
            "(shared_user_id IS NULL) <> (group_id IS NULL)",
            name=f"ck_{table}_target",
        ),
        sa.UniqueConstraint(item_column, "shared_user_id", name=f"uq_{table}_user"),
        sa.UniqueConstraint(item_column, "group_id", name=f"uq_{table}_group"),
    )
    op.create_index(f"ix_{table}_{item_column}", table, [item_column])
    op.create_index(f"ix_{table}_shared_user_id", table, ["shared_user_id"])
    op.create_index(f"ix_{table}_group_id", table, ["group_id"])


def upgrade() -> None:
    _create_share_table("brief_template_shares", "template_id", "brief_templates")
    _create_share_table("voice_profile_shares", "voice_profile_id", "voice_profiles")

    op.add_column("brief_templates", sa.Column("prompt", sa.Text(), nullable=True))
    op.add_column(
        "brief_templates",
        sa.Column(
            "voice_profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "voice_profiles.id",
                ondelete="SET NULL",
                name="fk_brief_templates_voice_profile_id",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "brief_templates", sa.Column("target_words", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("brief_templates", "target_words")
    op.drop_constraint(
        "fk_brief_templates_voice_profile_id", "brief_templates", type_="foreignkey"
    )
    op.drop_column("brief_templates", "voice_profile_id")
    op.drop_column("brief_templates", "prompt")
    op.drop_table("voice_profile_shares")
    op.drop_table("brief_template_shares")
