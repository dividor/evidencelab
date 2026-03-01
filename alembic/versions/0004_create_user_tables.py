"""Create user authentication and permissions tables.

Revision ID: 0004_create_user_tables
Revises: 2a4d7830d56f
Create Date: 2026-03-01 00:00:00
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0004_create_user_tables"
down_revision = "2a4d7830d56f"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Core user table (fastapi-users compatible)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(320) UNIQUE NOT NULL,
            hashed_password VARCHAR(1024) NOT NULL,
            display_name VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT true,
            is_verified BOOLEAN NOT NULL DEFAULT false,
            is_superuser BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # OAuth accounts (fastapi-users compatible)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS oauth_accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            oauth_name VARCHAR(100) NOT NULL,
            access_token VARCHAR(1024) NOT NULL,
            expires_at INTEGER,
            refresh_token VARCHAR(1024),
            account_id VARCHAR(320) NOT NULL,
            account_email VARCHAR(320)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_accounts_user_id "
        "ON oauth_accounts(user_id)"
    )

    # User groups for permissions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_groups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) UNIQUE NOT NULL,
            description TEXT,
            is_default BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # Group membership (many-to-many)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_group_members (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            group_id UUID NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, group_id)
        )
        """
    )

    # Group-to-datasource access permissions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS group_datasource_access (
            group_id UUID NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            datasource_key VARCHAR(255) NOT NULL,
            PRIMARY KEY (group_id, datasource_key)
        )
        """
    )

    # Seed default group with access to all data sources
    op.execute(
        """
        INSERT INTO user_groups (name, description, is_default)
        VALUES ('Default', 'Default group — access to all data sources', true)
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("group_datasource_access")
    op.drop_table("user_group_members")
    op.drop_table("user_groups")
    op.drop_table("oauth_accounts")
    op.drop_table("users")
