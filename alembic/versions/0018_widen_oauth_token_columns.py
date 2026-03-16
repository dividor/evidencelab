"""Widen OAuth token columns to TEXT.

Microsoft OAuth returns JWTs that exceed 1024 characters (typically
3400+ chars).  Change access_token and refresh_token from VARCHAR(1024)
to TEXT so all provider tokens fit.

Revision ID: 0018_widen_oauth_token_columns
Revises: 0017_allow_anonymous_ratings
Create Date: 2026-03-16
"""

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

revision = "0018_widen_oauth_token_columns"
down_revision = "0017_allow_anonymous_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "oauth_accounts",
        "access_token",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "oauth_accounts",
        "refresh_token",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "oauth_accounts",
        "refresh_token",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=True,
    )
    op.alter_column(
        "oauth_accounts",
        "access_token",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )
