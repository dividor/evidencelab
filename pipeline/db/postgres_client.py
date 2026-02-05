"""Postgres sidecar client for document/chunk metadata."""

from __future__ import annotations

from pipeline.db.postgres_client_admin import PostgresAdminMixin
from pipeline.db.postgres_client_base import PostgresClientBase
from pipeline.db.postgres_client_chunks import PostgresChunkMixin
from pipeline.db.postgres_client_docs import PostgresDocMixin
from pipeline.db.postgres_client_stats import PostgresStatsMixin


class PostgresClient(
    PostgresClientBase,
    PostgresAdminMixin,
    PostgresDocMixin,
    PostgresChunkMixin,
    PostgresStatsMixin,
):
    """Minimal Postgres client for docs/chunks sidecar tables."""

    _ALLOWED_MAP_FIELDS = {
        "map_title",
        "map_organization",
        "map_published_year",
        "map_document_type",
        "map_country",
        "map_language",
        "map_region",
        "map_theme",
        "map_pdf_url",
        "map_report_url",
        # Allow these sys fields as map fields for stats queries (they are in the DB schema)
        "sys_file_format",
        "sys_language",
    }
    _ALLOWED_SYS_FIELDS = {"sys_file_format", "sys_language"}
