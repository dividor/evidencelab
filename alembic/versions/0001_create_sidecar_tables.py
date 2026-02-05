"""Create Postgres sidecar tables for uneg.

Revision ID: 0001_create_sidecar_tables
Revises:
Create Date: 2026-01-27 00:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op  # type: ignore[attr-defined]

revision = "0001_create_sidecar_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "docs_uneg",
        sa.Column("doc_id", sa.Text(), primary_key=True),
        sa.Column("src_doc_raw_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("map_title", sa.Text(), nullable=True),
        sa.Column("map_organization", sa.Text(), nullable=True),
        sa.Column("map_published_year", sa.Text(), nullable=True),
        sa.Column("map_document_type", sa.Text(), nullable=True),
        sa.Column("map_country", sa.Text(), nullable=True),
        sa.Column("map_language", sa.Text(), nullable=True),
        sa.Column("map_region", sa.Text(), nullable=True),
        sa.Column("map_theme", sa.Text(), nullable=True),
        sa.Column("map_pdf_url", sa.Text(), nullable=True),
        sa.Column("map_report_url", sa.Text(), nullable=True),
        sa.Column("sys_summary", sa.Text(), nullable=True),
        sa.Column("sys_status", sa.Text(), nullable=True),
        sa.Column("sys_status_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sys_data", postgresql.JSONB(), nullable=True),
        sa.Column("sys_qdrant_legacy", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "chunks_uneg",
        sa.Column("chunk_id", sa.Text(), primary_key=True),
        sa.Column(
            "doc_id", sa.Text(), sa.ForeignKey("docs_uneg.doc_id", ondelete="CASCADE")
        ),
        sa.Column("sys_text", sa.Text(), nullable=True),
        sa.Column("sys_page_num", sa.Integer(), nullable=True),
        sa.Column("sys_headings", postgresql.JSONB(), nullable=True),
        sa.Column("tag_section_type", sa.Text(), nullable=True),
        sa.Column("sys_data", postgresql.JSONB(), nullable=True),
        sa.Column("sys_qdrant_legacy", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_chunks_uneg_doc_id", "chunks_uneg", ["doc_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_uneg_doc_id", table_name="chunks_uneg")
    op.drop_table("chunks_uneg")
    op.drop_table("docs_uneg")
