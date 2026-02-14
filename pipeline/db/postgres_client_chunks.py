"""Chunk queries for Postgres sidecar."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from psycopg2.extras import Json


class PostgresChunkMixin:
    """Chunk queries for Postgres sidecar."""

    chunks_table: str

    def _get_conn(self):
        raise NotImplementedError

    def ensure_sys_chunk_columns(self, sys_fields: Dict[str, Any]) -> None:
        raise NotImplementedError

    def ensure_chunk_tag_section_type(self) -> None:
        raise NotImplementedError

    def ensure_sys_chunk_taxonomies_column(self) -> None:
        raise NotImplementedError

    def ensure_qdrant_legacy_columns(self) -> None:
        raise NotImplementedError

    def upsert_chunk(
        self,
        *,
        chunk_id: str,
        doc_id: str,
        sys_text: Optional[str],
        sys_page_num: Optional[int],
        sys_headings: Optional[List[Any]],
        sys_heading_path: Optional[List[Any]],
        tag_section_type: Optional[str],
        sys_taxonomies: Optional[Dict[str, Any]] = None,
        sys_fields: Dict[str, Any],
        sys_qdrant_legacy: Optional[Dict[str, Any]] = None,
    ) -> None:
        if sys_fields:
            self.ensure_sys_chunk_columns(sys_fields)
        if tag_section_type is not None:
            self.ensure_chunk_tag_section_type()
        if sys_taxonomies:
            self.ensure_sys_chunk_taxonomies_column()
        if sys_qdrant_legacy is not None:
            self.ensure_qdrant_legacy_columns()
        extra_sys_columns = [
            key
            for key in sys_fields.keys()
            if key.startswith("sys_") and key not in {"sys_data", "sys_taxonomies"}
        ]
        columns = [
            "chunk_id",
            "doc_id",
            "sys_text",
            "sys_page_num",
            "sys_headings",
            "tag_section_type",
            "sys_taxonomies",
            "sys_data",
        ] + sorted(extra_sys_columns)
        if sys_qdrant_legacy is not None:
            columns.append("sys_qdrant_legacy")
        values = [
            chunk_id,
            doc_id,
            sys_text,
            sys_page_num,
            Json(sys_headings) if sys_headings is not None else None,
            tag_section_type,
            Json(sys_taxonomies) if sys_taxonomies else None,
            Json(sys_fields) if sys_fields else None,
        ]
        for key in sorted(extra_sys_columns):
            value = sys_fields.get(key)
            if isinstance(value, (dict, list)):
                values.append(Json(value))
            else:
                values.append(value)
        if sys_qdrant_legacy is not None:
            values.append(Json(sys_qdrant_legacy))
        assignments = [
            "doc_id = EXCLUDED.doc_id",
            "sys_text = EXCLUDED.sys_text",
            "sys_page_num = EXCLUDED.sys_page_num",
            "sys_headings = EXCLUDED.sys_headings",
            "tag_section_type = EXCLUDED.tag_section_type",
            "sys_taxonomies = EXCLUDED.sys_taxonomies",
            "sys_data = EXCLUDED.sys_data",
        ] + [f"{key} = EXCLUDED.{key}" for key in sorted(extra_sys_columns)]
        if sys_qdrant_legacy is not None:
            assignments.append("sys_qdrant_legacy = EXCLUDED.sys_qdrant_legacy")
        query = f"""
            INSERT INTO {self.chunks_table} ({", ".join(columns)})
            VALUES ({", ".join(["%s"] * len(columns))})
            ON CONFLICT (chunk_id) DO UPDATE
            SET {", ".join(assignments)}
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
            conn.commit()

    def merge_chunk_sys_fields(
        self,
        *,
        chunk_id: str,
        sys_fields: Dict[str, Any],
        tag_section_type: Optional[str] = None,
        sys_taxonomies: Optional[Dict[str, Any]] = None,
    ) -> None:
        if sys_fields:
            self.ensure_sys_chunk_columns(sys_fields)
        if sys_taxonomies:
            self.ensure_sys_chunk_taxonomies_column()
        if tag_section_type is not None:
            self.ensure_chunk_tag_section_type()

        assignments = ["sys_data = sys_data || %s"]
        values: List[Any] = [Json(sys_fields)]

        if tag_section_type is not None:
            assignments.append("tag_section_type = %s")
            values.append(tag_section_type)
        if sys_taxonomies is not None:
            assignments.append("sys_taxonomies = %s")
            values.append(Json(sys_taxonomies))

        extra_sys_columns = [
            key
            for key in sys_fields.keys()
            if key.startswith("sys_") and key not in {"sys_data", "sys_taxonomies"}
        ]

        for key in extra_sys_columns:
            assignments.append(f"{key} = %s")
            val = sys_fields[key]
            if isinstance(val, (dict, list)):
                values.append(Json(val))
            else:
                values.append(val)

        values.append(chunk_id)

        query = f"""
            UPDATE {self.chunks_table}
            SET {", ".join(assignments)}
            WHERE chunk_id = %s
        """

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
            conn.commit()

    def _clean_path(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return path

        # 1. Remove the specific bad prefix
        target = "evidencelab-ai/data-files/"
        if target in path:
            path = path.replace(target, "")

        # 2. Fix double data/data/ which might result from the above or exist independently
        if "data/data/" in path:
            path = path.replace("data/data/", "data/")

        return path

    def _clean_list_items(self, items: Optional[List[Any]], key: str) -> None:
        if not items:
            return
        for item in items:
            if isinstance(item, dict) and key in item:
                item[key] = self._clean_path(item[key])

    def _clean_chunk_paths(self, chunk_data: Dict[str, Any]) -> None:
        self._clean_list_items(chunk_data.get("sys_images"), "path")
        self._clean_list_items(chunk_data.get("sys_tables"), "image_path")

        elements = chunk_data.get("sys_chunk_elements")
        if elements:
            self._clean_list_items(elements, "path")
            self._clean_list_items(elements, "image_path")

    def fetch_chunks(self, chunk_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        ids = [str(chunk_id) for chunk_id in chunk_ids if chunk_id is not None]
        if not ids:
            return {}
        placeholders = ", ".join(["%s"] * len(ids))
        query = f"""
            SELECT chunk_id, doc_id, sys_text, sys_page_num, sys_headings,
                   tag_section_type, sys_taxonomies,
                   sys_data
            FROM {self.chunks_table}
            WHERE chunk_id IN ({placeholders})
        """
        rows: List[tuple] = []
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, ids)
                rows = cur.fetchall()
        results: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            (
                chunk_id,
                doc_id,
                sys_text,
                sys_page_num,
                sys_headings,
                tag_section_type,
                sys_taxonomies,
                sys_data,
            ) = row

            chunk_dict = {
                "id": chunk_id,
                "doc_id": doc_id,
                "sys_text": sys_text,
                "sys_page_num": sys_page_num,
                "sys_headings": sys_headings,
                "tag_section_type": tag_section_type,
                "sys_taxonomies": sys_taxonomies,
                "sys_data": sys_data,
                **(sys_data or {}),
            }

            # Clean paths to prevent 404s due to double prefix
            self._clean_chunk_paths(chunk_dict)

            results[str(chunk_id)] = chunk_dict
        return results

    def fetch_chunks_for_doc(self, doc_id: str) -> List[Dict[str, Any]]:
        query = f"""
            SELECT chunk_id, doc_id, sys_text, sys_page_num, sys_headings,
                   tag_section_type, sys_taxonomies,
                   sys_data
            FROM {self.chunks_table}
            WHERE doc_id = %s
        """
        rows: List[tuple] = []
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (doc_id,))
                rows = cur.fetchall()
        results = []
        for row in rows:
            (
                chunk_id,
                row_doc_id,
                sys_text,
                sys_page_num,
                sys_headings,
                tag_section_type,
                sys_taxonomies,
                sys_data,
            ) = row

            chunk_dict = {
                "id": chunk_id,
                "doc_id": row_doc_id,
                "sys_text": sys_text,
                "sys_page_num": sys_page_num,
                "sys_headings": sys_headings,
                "tag_section_type": tag_section_type,
                "sys_taxonomies": sys_taxonomies,
                "sys_data": sys_data,
                **(sys_data or {}),
            }

            # Clean paths
            self._clean_chunk_paths(chunk_dict)

            results.append(chunk_dict)
        return results

    def delete_chunks_for_doc(self, doc_id: str) -> int:
        """
        Delete all chunks for a specific document from Postgres.

        Args:
            doc_id: Document ID whose chunks should be deleted

        Returns:
            Number of deleted chunks
        """
        query = f"""
            DELETE FROM {self.chunks_table}
            WHERE doc_id = %s
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (doc_id,))
                deleted_count = cur.rowcount
            conn.commit()
        return deleted_count
