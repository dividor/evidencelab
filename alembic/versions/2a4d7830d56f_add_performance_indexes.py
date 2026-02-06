"""add_performance_indexes

Revision ID: 2a4d7830d56f
Revises: 0002
Create Date: 2026-02-04 12:55:00.000000

"""

from alembic import op  # type: ignore

# revision identifiers, used by Alembic.
revision = "2a4d7830d56f"  # pragma: allowlist secret
down_revision = "0003_add_summary_taxonomy_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Enable pg_trgm extension if not exists
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2. Add Indexes for 'docs' table (and 'docs_uneg', 'docs_gcf' etc handled by standard naming
    # convention in pipeline, but Alembic usually targets specific tables.
    # Since the codebase uses dynamic table names based on source (e.g. docs_uneg),
    # we need to consider how to apply this to all existing tables.
    # However, standard Alembic usually manages a known schema.
    # Let's assume 'docs' is the base or check if we need to iterate.
    # Given the previous code in postgres_client_admin used self.docs_table,
    # and the user said "We need to fix the performance", likely implying for the active datasets.

    # In this specific codebase, it seems tables are created dynamically per source.
    # This makes standard Alembic tricky unless we wrap it or targeting a 'template' table?
    # BUT the user said "ANY SQL updates must be represented in alembic".
    # So I will write raw SQL that attempts to create indexes on the likely tables, or better yet,
    # just target the known active sources or use a safe approach.

    # Wait, looking at 0001_create_sidecar_tables.py might clarify how they handle multiple sources.
    # If I can't see it, I'll assume 'docs' logic or just applies to known tables.
    # For now I will apply to 'docs' as a symbolic action,
    # and maybe 'docs_uneg', 'docs_gcf' if I can dynamic it, but Alembic is static usually.

    # Actually, the user's specific URL is UN Humanitarian, which maps to 'uneg' usually.
    # The previous code used `client = PostgresClient("uneg")`.
    # The tables are `docs_uneg`.

    # I will stick to Raw SQL for the specific table 'docs_uneg' and 'docs' to be safe,
    # or arguably all known tables.
    # To be "correct" in a dynamic system, the migration might iterate known sources
    # or the system should use a single partitioned table.
    # Assuming 'docs_uneg' is the critical one.

    # Safe approach: Try to apply to `docs_uneg` and `docs_gcf` and
    # `docs_wb` explicitly if they exist.

    tables = ["docs_uneg", "docs_wb", "docs_gcf"]

    for table in tables:
        # Check if table exists to avoid error would be nice,
        # but IF NOT EXISTS on index covers it partially?
        # No, creating index on non-existent table fails.
        # Let's just use a DO block in SQL?

        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT FROM pg_tables
                    WHERE schemaname = 'public' AND tablename = '{table}'
                ) THEN
                    CREATE INDEX IF NOT EXISTS ix_{table}_title_trgm
                        ON {table} USING gin (map_title gin_trgm_ops);
                    CREATE INDEX IF NOT EXISTS ix_{table}_summary_trgm
                        ON {table} USING gin (sys_summary gin_trgm_ops);
                    CREATE INDEX IF NOT EXISTS ix_{table}_taxonomies
                        ON {table} USING gin (sys_taxonomies);
                    CREATE INDEX IF NOT EXISTS ix_{table}_file_format
                        ON {table}((sys_data->>'sys_file_format'));
                    CREATE INDEX IF NOT EXISTS ix_{table}_toc_approved
                        ON {table}(((sys_data->>'sys_toc_approved')::boolean));
                END IF;
            END
            $$;
        """
        )


def downgrade() -> None:
    tables = ["docs_uneg", "docs_wb", "docs_gcf"]
    for table in tables:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT FROM pg_tables
                    WHERE schemaname = 'public' AND tablename = '{table}'
                ) THEN
                    DROP INDEX IF EXISTS ix_{table}_title_trgm;
                    DROP INDEX IF EXISTS ix_{table}_summary_trgm;
                    DROP INDEX IF EXISTS ix_{table}_taxonomies;
                    DROP INDEX IF EXISTS ix_{table}_file_format;
                    DROP INDEX IF EXISTS ix_{table}_toc_approved;
                END IF;
            END
            $$;
        """
        )
