"""Create Postgres sidecar tables for uneg.

Revision ID: 0001_create_sidecar_tables
Revises:
Create Date: 2026-01-27 00:00:00
"""

from alembic import op  # type: ignore[attr-defined]

revision = "0001_create_sidecar_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Use raw SQL so we can use IF NOT EXISTS for idempotency
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS docs_uneg (
            doc_id TEXT PRIMARY KEY,
            src_doc_raw_metadata JSONB,
            map_title TEXT,
            map_organization TEXT,
            map_published_year TEXT,
            map_document_type TEXT,
            map_country TEXT,
            map_language TEXT,
            map_region TEXT,
            map_theme TEXT,
            map_pdf_url TEXT,
            map_report_url TEXT,
            sys_summary TEXT,
            sys_status TEXT,
            sys_status_timestamp TIMESTAMPTZ,
            sys_data JSONB,
            sys_qdrant_legacy JSONB
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks_uneg (
            chunk_id TEXT PRIMARY KEY,
            doc_id TEXT REFERENCES docs_uneg(doc_id) ON DELETE CASCADE,
            sys_text TEXT,
            sys_page_num INTEGER,
            sys_headings JSONB,
            tag_section_type TEXT,
            sys_data JSONB,
            sys_qdrant_legacy JSONB
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_uneg_doc_id ON chunks_uneg (doc_id)"
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_uneg_doc_id", table_name="chunks_uneg")
    op.drop_table("chunks_uneg")
    op.drop_table("docs_uneg")
