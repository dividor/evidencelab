"""Admin helpers for Postgres sidecar tables."""

from __future__ import annotations

from typing import List


class PostgresAdminMixin:
    """Administrative helpers for Postgres sidecar tables."""

    docs_table: str
    chunks_table: str
    _ensured_doc_sys_columns: set[str]
    _ensured_chunk_sys_columns: set[str]

    def _get_conn(self):
        raise NotImplementedError

    def fetch_existing_doc_ids(self) -> List[str]:
        query = f"SELECT doc_id FROM {self.docs_table}"
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [str(row[0]) for row in cur.fetchall()]

    def fetch_existing_chunk_ids(self) -> List[str]:
        query = f"SELECT chunk_id FROM {self.chunks_table}"
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [str(row[0]) for row in cur.fetchall()]

    def truncate_tables(self) -> None:
        query = f"TRUNCATE TABLE {self.docs_table}, {self.chunks_table}"
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_sidecar_tables(self) -> None:
        create_docs = f"""
            CREATE TABLE IF NOT EXISTS {self.docs_table} (
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
                sys_taxonomies JSONB,
                sys_status TEXT,
                sys_status_timestamp TIMESTAMPTZ,
                sys_file_format TEXT,
                sys_data JSONB,
                sys_qdrant_legacy JSONB
            )
        """
        create_chunks = f"""
            CREATE TABLE IF NOT EXISTS {self.chunks_table} (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT REFERENCES {self.docs_table}(doc_id) ON DELETE CASCADE,
                sys_text TEXT,
                sys_page_num INTEGER,
                sys_headings JSONB,
                tag_section_type TEXT,
                sys_taxonomies JSONB,
                sys_data JSONB,
                sys_qdrant_legacy JSONB
            )
        """
        create_index = f"""
            CREATE INDEX IF NOT EXISTS ix_{self.chunks_table}_doc_id
            ON {self.chunks_table}(doc_id)
        """
        # Indexes for stats and filtering
        create_docs_indexes = [
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_org "
            f"ON {self.docs_table}(map_organization)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_type "
            f"ON {self.docs_table}(map_document_type)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_year "
            f"ON {self.docs_table}(map_published_year)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_lang "
            f"ON {self.docs_table}(map_language)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_status "
            f"ON {self.docs_table}(sys_status)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_params "
            f"ON {self.docs_table}(map_organization, map_published_year, map_document_type)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_ts "
            f"ON {self.docs_table}(sys_status_timestamp DESC)",
            # Composite indexes for stats aggregation
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_org_status "
            f"ON {self.docs_table}(map_organization, sys_status)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_type_status "
            f"ON {self.docs_table}(map_document_type, sys_status)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_year_status "
            f"ON {self.docs_table}(map_published_year, sys_status)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_lang_status "
            f"ON {self.docs_table}(map_language, sys_status)",
            f"CREATE INDEX IF NOT EXISTS ix_{self.docs_table}_format_status "
            f"ON {self.docs_table}(sys_file_format, sys_status)",
            # Search optimization (requires pg_trgm)
            # MOVED TO ALEMBIC MIGRATION 0003
            # JSONB optimization
            # MOVED TO ALEMBIC MIGRATION 0003
        ]

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                cur.execute(create_docs)
                cur.execute(create_chunks)
                cur.execute(create_index)
            conn.commit()

        # Run column migrations BEFORE index creation (indexes may depend on columns)
        self.ensure_sys_file_format_column()
        self.ensure_sys_doc_taxonomies_column()
        self.ensure_sys_chunk_taxonomies_column()
        self.ensure_doc_raw_metadata_column()
        self.ensure_sys_status_columns()
        self.ensure_chunk_tag_section_type()

        # Create indexes after columns exist
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                for idx_sql in create_docs_indexes:
                    cur.execute(idx_sql)
            conn.commit()

    def ensure_sys_status_columns(self) -> None:
        query = f"""
            ALTER TABLE {self.docs_table}
                ADD COLUMN IF NOT EXISTS sys_status TEXT,
                ADD COLUMN IF NOT EXISTS sys_status_timestamp TIMESTAMPTZ
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_chunk_tag_section_type(self) -> None:
        query = f"""
            ALTER TABLE {self.chunks_table}
                ADD COLUMN IF NOT EXISTS tag_section_type TEXT
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_sys_file_format_column(self) -> None:
        """Add sys_file_format column if missing (for tables created before this column)."""
        query = f"""
            ALTER TABLE {self.docs_table}
                ADD COLUMN IF NOT EXISTS sys_file_format TEXT
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_doc_raw_metadata_column(self) -> None:
        query = f"""
            ALTER TABLE {self.docs_table}
                ADD COLUMN IF NOT EXISTS src_doc_raw_metadata JSONB
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_sys_doc_taxonomies_column(self) -> None:
        query = f"""
            ALTER TABLE {self.docs_table}
                ADD COLUMN IF NOT EXISTS sys_taxonomies JSONB
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_sys_chunk_taxonomies_column(self) -> None:
        query = f"""
            ALTER TABLE {self.chunks_table}
                ADD COLUMN IF NOT EXISTS sys_taxonomies JSONB
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_sys_doc_columns(self, sys_fields: dict) -> None:
        if not sys_fields:
            return

        def _infer_type(key: str, value: object) -> str:
            if key.endswith("_timestamp"):
                return "TIMESTAMPTZ"
            if isinstance(value, bool):
                return "BOOLEAN"
            if isinstance(value, int):
                return "BIGINT"
            if isinstance(value, float):
                return "DOUBLE PRECISION"
            if isinstance(value, (dict, list)):
                return "JSONB"
            return "TEXT"

        additions = []
        for key, value in sys_fields.items():
            if not key.startswith("sys_"):
                continue
            if key in {"sys_data", "sys_summary"}:
                continue
            if key in self._ensured_doc_sys_columns:
                continue
            additions.append(
                f"ADD COLUMN IF NOT EXISTS {key} {_infer_type(key, value)}"
            )
            self._ensured_doc_sys_columns.add(key)

        if not additions:
            return

        query = f"ALTER TABLE {self.docs_table} {', '.join(additions)}"
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_sys_chunk_columns(self, sys_fields: dict) -> None:
        if not sys_fields:
            return

        def _infer_type(key: str, value: object) -> str:
            if key.endswith("_timestamp"):
                return "TIMESTAMPTZ"
            if isinstance(value, bool):
                return "BOOLEAN"
            if isinstance(value, int):
                return "BIGINT"
            if isinstance(value, float):
                return "DOUBLE PRECISION"
            if isinstance(value, (dict, list)):
                return "JSONB"
            return "TEXT"

        additions = []
        for key, value in sys_fields.items():
            if not key.startswith("sys_"):
                continue
            if key == "sys_data":
                continue
            if key in self._ensured_chunk_sys_columns:
                continue
            additions.append(
                f"ADD COLUMN IF NOT EXISTS {key} {_infer_type(key, value)}"
            )
            self._ensured_chunk_sys_columns.add(key)

        if not additions:
            return

        query = f"ALTER TABLE {self.chunks_table} {', '.join(additions)}"
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

    def ensure_qdrant_legacy_columns(self) -> None:
        query = f"""
            ALTER TABLE {self.docs_table}
                ADD COLUMN IF NOT EXISTS sys_qdrant_legacy JSONB
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()

        query = f"""
            ALTER TABLE {self.chunks_table}
                ADD COLUMN IF NOT EXISTS sys_qdrant_legacy JSONB
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()
