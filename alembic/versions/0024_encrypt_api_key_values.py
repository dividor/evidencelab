"""Expand key_value column to 512 chars to hold Fernet-encrypted tokens.

API key values are now encrypted at rest using Fernet symmetric encryption
(utils.encryption).  A Fernet token for a ~46-char API key is ~140 chars;
512 provides ample headroom.

Existing plaintext values (if any) remain readable — utils.encryption
detects them via the absence of the ``gAAAAA`` Fernet prefix and logs a
warning.  Admins should regenerate old keys to get them encrypted.

Revision ID: 0024_encrypt_api_key_values
Revises: 0023_add_key_value_to_api_keys
Create Date: 2026-03-29
"""

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

revision = "0024_encrypt_api_key_values"  # pragma: allowlist secret
down_revision = "0023_add_key_value_to_api_keys"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand the column to accommodate Fernet-encrypted tokens (~140 chars)
    op.alter_column(
        "api_keys",
        "key_value",
        existing_type=sa.String(255),
        type_=sa.String(512),
        existing_nullable=True,
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "api_keys",
        "key_value",
        existing_type=sa.String(512),
        type_=sa.String(255),
        existing_nullable=True,
        nullable=True,
    )
