"""Merge two 0024 heads: audit log protocol column and API key encryption.

Revision ID: 0025_merge_0024_heads
Revises: 0024_mcp_audit_protocol, 0024_encrypt_api_key_values
Create Date: 2026-03-29

"""

revision = "0025_merge_0024_heads"
down_revision = ("0024_mcp_audit_protocol", "0024_encrypt_api_key_values")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
