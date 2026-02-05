"""Document queries for Postgres sidecar."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from psycopg2.extras import Json


def _normalize_sys_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize_sys_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_normalize_sys_value(val) for val in value]
    if isinstance(value, tuple):
        return [_normalize_sys_value(val) for val in value]
    return value


def _resolve_sys_status(
    sys_fields: Dict[str, Any],
    existing: Dict[str, Any],
    extract_status_timestamp: Callable[[Dict[str, Any]], Optional[datetime]],
) -> Tuple[Dict[str, Any], Optional[datetime], bool]:
    merged = dict(existing)
    merged.update(sys_fields)
    update_status_timestamp = (
        "sys_status_timestamp" in sys_fields or "sys_stages" in sys_fields
    )
    resolved_timestamp = None
    if "sys_status_timestamp" in sys_fields:
        resolved_timestamp = merged.get("sys_status_timestamp")
    elif "sys_stages" in sys_fields:
        resolved_timestamp = extract_status_timestamp(merged)
        if resolved_timestamp is not None and "sys_status_timestamp" not in merged:
            merged["sys_status_timestamp"] = resolved_timestamp
    return merged, resolved_timestamp, update_status_timestamp


def _collect_extra_sys_columns(sys_fields: Dict[str, Any]) -> List[str]:
    return [
        key
        for key in sys_fields.keys()
        if key.startswith("sys_")
        and key
        not in {
            "sys_status",
            "sys_status_timestamp",
            "sys_data",
            "sys_summary",
            "sys_taxonomies",
        }
    ]


def _append_sys_field_value(
    values: List[Any],
    key: str,
    value: Any,
    normalize_timestamp: Callable[[Any], Optional[datetime]],
) -> None:
    if isinstance(value, (dict, list)):
        values.append(Json(value))
    elif key.endswith("_timestamp"):
        values.append(normalize_timestamp(value))
    else:
        values.append(value)


def _build_doc_columns(
    map_fields: Dict[str, Any],
    extra_sys_columns: List[str],
    include_qdrant_legacy: bool,
) -> List[str]:
    columns = [
        "doc_id",
        "src_doc_raw_metadata",
        "sys_summary",
        "sys_taxonomies",
        "sys_status",
        "sys_status_timestamp",
        "sys_data",
    ] + sorted(map_fields.keys())
    columns += sorted(extra_sys_columns)
    if include_qdrant_legacy:
        columns.append("sys_qdrant_legacy")
    return columns


def _build_doc_assignments(
    map_fields: Dict[str, Any],
    extra_sys_columns: List[str],
    include_qdrant_legacy: bool,
) -> List[str]:
    assignments = [
        "src_doc_raw_metadata = EXCLUDED.src_doc_raw_metadata",
        "sys_summary = EXCLUDED.sys_summary",
        "sys_taxonomies = EXCLUDED.sys_taxonomies",
        "sys_status = EXCLUDED.sys_status",
        "sys_status_timestamp = EXCLUDED.sys_status_timestamp",
        "sys_data = EXCLUDED.sys_data",
    ]
    assignments += [f"{key} = EXCLUDED.{key}" for key in sorted(map_fields.keys())]
    assignments += [f"{key} = EXCLUDED.{key}" for key in sorted(extra_sys_columns)]
    if include_qdrant_legacy:
        assignments.append("sys_qdrant_legacy = EXCLUDED.sys_qdrant_legacy")
    return assignments


class PostgresDocMixin:
    """Document queries for Postgres sidecar."""

    docs_table: str

    def _get_conn(self):
        raise NotImplementedError

    def _normalize_timestamp(
        self, value: Optional[datetime | str]
    ) -> Optional[datetime]:
        raise NotImplementedError

    def _extract_status_timestamp(
        self, sys_fields: Dict[str, Any]
    ) -> Optional[datetime]:
        raise NotImplementedError

    def ensure_sys_doc_columns(self, sys_fields: Dict[str, Any]) -> None:
        raise NotImplementedError

    def ensure_sys_doc_taxonomies_column(self) -> None:
        raise NotImplementedError

    def ensure_qdrant_legacy_columns(self) -> None:
        raise NotImplementedError

    def upsert_doc(
        self,
        *,
        doc_id: str,
        src_doc_raw_metadata: Optional[Dict[str, Any]],
        map_fields: Dict[str, Any],
        sys_summary: Optional[str],
        sys_taxonomies: Optional[Dict[str, Any]] = None,
        sys_fields: Dict[str, Any],
        sys_qdrant_legacy: Optional[Dict[str, Any]] = None,
        sys_status: Optional[str] = None,
        sys_status_timestamp: Optional[datetime | str] = None,
    ) -> None:
        if sys_fields:
            self.ensure_sys_doc_columns(sys_fields)
        if sys_qdrant_legacy is not None:
            self.ensure_qdrant_legacy_columns()
        resolved_status = sys_status or sys_fields.get("sys_status")
        resolved_timestamp = (
            sys_status_timestamp
            or sys_fields.get("sys_status_timestamp")
            or self._extract_status_timestamp(sys_fields)
        )
        if resolved_timestamp and "sys_status_timestamp" not in sys_fields:
            sys_fields["sys_status_timestamp"] = (
                resolved_timestamp.isoformat()
                if isinstance(resolved_timestamp, datetime)
                else resolved_timestamp
            )
        extra_sys_columns = _collect_extra_sys_columns(sys_fields)
        columns = _build_doc_columns(
            map_fields,
            extra_sys_columns,
            include_qdrant_legacy=sys_qdrant_legacy is not None,
        )
        values = [
            doc_id,
            Json(src_doc_raw_metadata) if src_doc_raw_metadata is not None else None,
            sys_summary,
            Json(sys_taxonomies) if sys_taxonomies else None,
            resolved_status,
            self._normalize_timestamp(resolved_timestamp),
            Json(sys_fields) if sys_fields else None,
        ] + [map_fields.get(key) for key in sorted(map_fields.keys())]
        for key in sorted(extra_sys_columns):
            _append_sys_field_value(
                values,
                key,
                sys_fields.get(key),
                self._normalize_timestamp,
            )
        if sys_qdrant_legacy is not None:
            values.append(Json(sys_qdrant_legacy))

        assignments = _build_doc_assignments(
            map_fields,
            extra_sys_columns,
            include_qdrant_legacy=sys_qdrant_legacy is not None,
        )

        query = f"""
            INSERT INTO {self.docs_table} ({", ".join(columns)})
            VALUES ({", ".join(["%s"] * len(columns))})
            ON CONFLICT (doc_id) DO UPDATE
            SET {", ".join(assignments)}
        """

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
            conn.commit()

    def merge_doc_sys_fields(
        self,
        *,
        doc_id: str,
        sys_fields: Dict[str, Any],
        sys_summary: Optional[str] = None,
        sys_taxonomies: Optional[Dict[str, Any]] = None,
    ) -> None:
        if sys_fields:
            self.ensure_sys_doc_columns(sys_fields)
        if sys_taxonomies:
            self.ensure_sys_doc_taxonomies_column()
        if "sys_status" in sys_fields and "sys_last_updated" not in sys_fields:
            sys_fields["sys_last_updated"] = time.time()
        if "sys_status_timestamp" in sys_fields:
            sys_fields["sys_status_timestamp"] = self._normalize_timestamp(
                sys_fields.get("sys_status_timestamp")
            )
        existing = self.fetch_doc_sys_fields([doc_id]).get(str(doc_id), {})
        merged, resolved_timestamp, update_status_timestamp = _resolve_sys_status(
            sys_fields, existing, self._extract_status_timestamp
        )

        merged = _normalize_sys_value(merged)

        assignments = ["sys_data = %s"]
        values: List[Any] = [Json(merged)]
        if sys_summary is not None:
            assignments.append("sys_summary = %s")
            values.append(sys_summary)
        if sys_taxonomies is not None:
            assignments.append("sys_taxonomies = %s")
            values.append(Json(sys_taxonomies))
        if "sys_status" in sys_fields:
            assignments.append("sys_status = %s")
            values.append(sys_fields.get("sys_status"))
        if update_status_timestamp:
            assignments.append("sys_status_timestamp = %s")
            values.append(self._normalize_timestamp(resolved_timestamp))
        for key, value in sys_fields.items():
            if not key.startswith("sys_"):
                continue
            if key in {
                "sys_status",
                "sys_status_timestamp",
                "sys_data",
                "sys_summary",
                "sys_taxonomies",
            }:
                continue
            assignments.append(f"{key} = %s")
            _append_sys_field_value(
                values,
                key,
                value,
                self._normalize_timestamp,
            )

        values.append(doc_id)
        query = f"""
            UPDATE {self.docs_table}
            SET {", ".join(assignments)}
            WHERE doc_id = %s
        """

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
            conn.commit()

    def fetch_docs(self, doc_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        ids = [str(doc_id) for doc_id in doc_ids if doc_id is not None]
        if not ids:
            return {}
        placeholders = ", ".join(["%s"] * len(ids))
        query = f"""
            SELECT
                doc_id,
                src_doc_raw_metadata,
                sys_summary,
                sys_full_summary,
                sys_taxonomies,
                sys_status,
                sys_status_timestamp,
                sys_data,
                map_title,
                map_organization,
                map_published_year,
                map_document_type,
                map_country,
                map_language,
                map_region,
                map_theme,
                map_pdf_url,
                map_report_url
            FROM {self.docs_table}
            WHERE doc_id IN ({placeholders})
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, ids)
                rows = cur.fetchall()
        results: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            (
                doc_id,
                src_doc_raw_metadata,
                sys_summary,
                sys_full_summary,
                sys_taxonomies,
                sys_status,
                sys_status_timestamp,
                sys_data,
                map_title,
                map_organization,
                map_published_year,
                map_document_type,
                map_country,
                map_language,
                map_region,
                map_theme,
                map_pdf_url,
                map_report_url,
            ) = row
            sys_toc = None
            sys_toc_classified = None
            if isinstance(sys_data, dict):
                sys_toc = sys_data.get("sys_toc")
                sys_toc_classified = sys_data.get("sys_toc_classified")
            payload = {
                "id": doc_id,
                "src_doc_raw_metadata": src_doc_raw_metadata,
                "sys_summary": sys_summary,
                "sys_full_summary": sys_full_summary,
                "sys_taxonomies": sys_taxonomies,
                "sys_status": sys_status,
                "sys_status_timestamp": sys_status_timestamp,
                "sys_data": sys_data,
                "sys_toc": sys_toc,
                "sys_toc_classified": sys_toc_classified,
                "map_title": map_title,
                "map_organization": map_organization,
                "map_published_year": map_published_year,
                "map_document_type": map_document_type,
                "map_country": map_country,
                "map_language": map_language,
                "map_region": map_region,
                "map_theme": map_theme,
                "map_pdf_url": map_pdf_url,
                "map_report_url": map_report_url,
            }
            results[str(doc_id)] = payload
        return results

    def fetch_doc_sys_fields(
        self, doc_ids: Optional[Iterable[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        params: List[Any] = []
        where_clause = ""
        if doc_ids:
            ids = [str(doc_id) for doc_id in doc_ids if doc_id is not None]
            if ids:
                placeholders = ", ".join(["%s"] * len(ids))
                where_clause = f"WHERE doc_id IN ({placeholders})"
                params = list(ids)
        query = f"""
            SELECT doc_id, sys_data
            FROM {self.docs_table}
            {where_clause}
        """
        results: Dict[str, Dict[str, Any]] = {}
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                for doc_id, sys_data in cur.fetchall():
                    results[str(doc_id)] = sys_data or {}
        return results

    def fetch_docs_by_status(
        self, status: str, year: int | None = None
    ) -> List[Dict[str, Any]]:
        params: List[Any] = [status]
        year_clause = ""
        if year is not None:
            year_clause = "AND map_published_year = %s"
            params.append(str(year))
        query = f"""
            SELECT doc_id, sys_data, map_title, map_organization, map_published_year,
                   map_document_type, map_country, map_language, map_region, map_theme,
                   map_pdf_url, map_report_url, sys_status
            FROM {self.docs_table}
            WHERE sys_data ->> 'sys_status' = %s
            {year_clause}
        """
        rows: List[tuple] = []
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        results = []
        for row in rows:
            (
                doc_id,
                sys_data,
                map_title,
                map_organization,
                map_published_year,
                map_document_type,
                map_country,
                map_language,
                map_region,
                map_theme,
                map_pdf_url,
                map_report_url,
                sys_status,
            ) = row
            sys_filepath = None
            sys_parsed_folder = None
            if isinstance(sys_data, dict):
                sys_filepath = sys_data.get("sys_filepath")
                sys_parsed_folder = sys_data.get("sys_parsed_folder")

            results.append(
                {
                    "id": doc_id,
                    "sys_data": sys_data,
                    "sys_filepath": sys_filepath,
                    "sys_parsed_folder": sys_parsed_folder,
                    "map_title": map_title,
                    "map_organization": map_organization,
                    "map_published_year": map_published_year,
                    "map_document_type": map_document_type,
                    "map_country": map_country,
                    "map_language": map_language,
                    "map_region": map_region,
                    "map_theme": map_theme,
                    "map_pdf_url": map_pdf_url,
                    "map_report_url": map_report_url,
                    "sys_status": sys_status,
                }
            )
        return results

    def delete_docs_by_title(self, title: str) -> List[str]:
        query = f"""
            DELETE FROM {self.docs_table}
            WHERE map_title = %s
            RETURNING doc_id
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (title,))
                deleted_ids = [str(row[0]) for row in cur.fetchall()]
            conn.commit()
        return deleted_ids

    def fetch_doc_ids_by_title(self, title: str, limit: int = 5000) -> List[str]:
        query = f"""
            SELECT doc_id
            FROM {self.docs_table}
            WHERE map_title ILIKE %s
            LIMIT %s
        """
        rows: List[tuple] = []
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (f"%{title}%", limit))
                rows = cur.fetchall()
        return [str(row[0]) for row in rows]

    def fetch_all_docs(self) -> List[Dict[str, Any]]:
        query = f"""
            SELECT
                doc_id,
                src_doc_raw_metadata,
                sys_summary,
                sys_taxonomies,
                sys_status,
                sys_status_timestamp,
                sys_data,
                map_title,
                map_organization,
                map_published_year,
                map_document_type,
                map_country,
                map_language,
                map_region,
                map_theme,
                map_pdf_url,
                map_report_url
            FROM {self.docs_table}
        """
        rows: List[tuple] = []
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            (
                doc_id,
                src_doc_raw_metadata,
                sys_summary,
                sys_taxonomies,
                sys_status,
                sys_status_timestamp,
                sys_data,
                map_title,
                map_organization,
                map_published_year,
                map_document_type,
                map_country,
                map_language,
                map_region,
                map_theme,
                map_pdf_url,
                map_report_url,
            ) = row
            sys_filepath = None
            sys_parsed_folder = None
            if isinstance(sys_data, dict):
                sys_filepath = sys_data.get("sys_filepath")
                sys_parsed_folder = sys_data.get("sys_parsed_folder")
            results.append(
                {
                    "id": doc_id,
                    "src_doc_raw_metadata": src_doc_raw_metadata,
                    "sys_summary": sys_summary,
                    "sys_taxonomies": sys_taxonomies,
                    "sys_status": sys_status,
                    "sys_status_timestamp": sys_status_timestamp,
                    "sys_data": sys_data,
                    "sys_filepath": sys_filepath,
                    "sys_parsed_folder": sys_parsed_folder,
                    "map_title": map_title,
                    "map_organization": map_organization,
                    "map_published_year": map_published_year,
                    "map_document_type": map_document_type,
                    "map_country": map_country,
                    "map_language": map_language,
                    "map_region": map_region,
                    "map_theme": map_theme,
                    "map_pdf_url": map_pdf_url,
                    "map_report_url": map_report_url,
                }
            )
        return results

    def fetch_years_for_status(self, status: str) -> List[str]:
        query = f"""
            SELECT DISTINCT map_published_year
            FROM {self.docs_table}
            WHERE sys_data ->> 'sys_status' = %s
              AND map_published_year IS NOT NULL
              AND map_published_year <> ''
        """
        rows: List[tuple] = []
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (status,))
                rows = cur.fetchall()
        return [str(row[0]) for row in rows if row and row[0] is not None]

    def fetch_docs_by_file_checksum(
        self, checksum: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        columns = [
            "doc_id",
            "src_doc_raw_metadata",
            "sys_summary",
            "sys_taxonomies",
            "sys_data",
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
        ]
        query = f"""
            SELECT {", ".join(columns)}
            FROM {self.docs_table}
            WHERE sys_data ->> 'sys_file_checksum' = %s
            LIMIT %s
        """
        rows: List[tuple] = []
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (checksum, limit))
                rows = cur.fetchall()
        results = []
        for row in rows:
            (
                doc_id,
                src_doc_raw_metadata,
                sys_summary,
                sys_taxonomies,
                sys_data,
                map_title,
                map_organization,
                map_published_year,
                map_document_type,
                map_country,
                map_language,
                map_region,
                map_theme,
                map_pdf_url,
                map_report_url,
            ) = row
            results.append(
                {
                    "id": doc_id,
                    "src_doc_raw_metadata": src_doc_raw_metadata,
                    "sys_summary": sys_summary,
                    "sys_taxonomies": sys_taxonomies,
                    "sys_data": sys_data,
                    "map_title": map_title,
                    "map_organization": map_organization,
                    "map_published_year": map_published_year,
                    "map_document_type": map_document_type,
                    "map_country": map_country,
                    "map_language": map_language,
                    "map_region": map_region,
                    "map_theme": map_theme,
                    "map_pdf_url": map_pdf_url,
                    "map_report_url": map_report_url,
                }
            )
        return results

    def fetch_doc_by_sys_filepath(self, sys_filepath: str) -> Optional[Dict[str, Any]]:

        query = f"""
            SELECT
                doc_id, src_doc_raw_metadata, sys_summary, sys_taxonomies, sys_data,
                map_title, map_organization, map_published_year, map_document_type,
                map_country, map_language, map_region, map_theme, map_pdf_url,
                map_report_url
            FROM {self.docs_table}
            WHERE sys_data ->> 'sys_filepath' = %s
            LIMIT 1
        """
        row = None
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (sys_filepath,))
                row = cur.fetchone()
        if not row:
            return None
        (
            doc_id,
            src_doc_raw_metadata,
            sys_summary,
            sys_taxonomies,
            sys_data,
            map_title,
            map_organization,
            map_published_year,
            map_document_type,
            map_country,
            map_language,
            map_region,
            map_theme,
            map_pdf_url,
            map_report_url,
        ) = row
        sys_status = None
        sys_chunk_count = None
        sys_filepath = None
        sys_parsed_folder = None
        if isinstance(sys_data, dict):
            sys_status = sys_data.get("sys_status")
            sys_chunk_count = sys_data.get("sys_chunk_count")
            sys_filepath = sys_data.get("sys_filepath")
            sys_parsed_folder = sys_data.get("sys_parsed_folder")
        return {
            "id": doc_id,
            "doc_id": doc_id,
            "src_doc_raw_metadata": src_doc_raw_metadata,
            "sys_summary": sys_summary,
            "sys_taxonomies": sys_taxonomies,
            "sys_data": sys_data,
            "sys_status": sys_status,
            "sys_chunk_count": sys_chunk_count,
            "sys_filepath": sys_filepath,
            "sys_parsed_folder": sys_parsed_folder,
            "map_report_url": map_report_url,
        }

    def get_paginated_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, Any]] = None,
        sort_by: str = "year",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """
        Get documents with pagination, filtering and sorting.
        Mimics the behavior of Database.get_paginated_documents but using Postgres.
        """
        if filters is None:
            filters = {}

        # Mappings for filter fields to DB columns
        filter_map = {
            "organization": "map_organization",
            "document_type": "map_document_type",
            "published_year": "map_published_year",
            "language": "map_language",
            "file_format": "sys_data ->> 'sys_file_format'",
            "status": "sys_status",
            "sdg": "sys_taxonomies ->> 'sdg'",
            "date": "sys_status_timestamp",
        }

        return self._get_paginated_documents_impl(
            page, page_size, filters, filter_map, sort_by, sort_order
        )

    def _build_filter_clauses(
        self, filters: Dict[str, Any], filter_map: Dict[str, str]
    ) -> Tuple[List[str], List[Any]]:
        where_clauses = []
        params = []

        for key, value in filters.items():
            if not value:
                continue

            if key == "title":
                where_clauses.append("map_title ILIKE %s")
                params.append(f"%{value}%")
            elif key == "search":
                term = f"%{value}%"
                where_clauses.append("(map_title ILIKE %s OR sys_summary ILIKE %s)")
                params.extend([term, term])
            elif key == "toc_approved":
                if str(value).lower() == "true":
                    where_clauses.append(
                        "(sys_data ->> 'sys_toc_approved')::boolean IS TRUE"
                    )
                else:
                    cond = "(sys_data ->> 'sys_toc_approved')::boolean IS NOT TRUE"
                    where_clauses.append(
                        f"({cond} OR sys_data ->> 'sys_toc_approved' IS NULL)"
                    )
            elif key in ("sdg", "cross_cutting_theme"):
                # Handle taxonomy filters (support lists for multiselect)
                if isinstance(value, list) and value:
                    # Check if requested taxonomy codes exist in document's array
                    # sys_taxonomies->'{key}' is JSONB array: [{"code": "sdg1"}]
                    # Check if any code in array matches filter values
                    conditions = []
                    for tax_code in value:
                        # Use jsonb_path_exists to check for matching code
                        path_expr = f'$.{key}[*].code ? (@ == "{tax_code}")'
                        conditions.append(
                            f"jsonb_path_exists(sys_taxonomies, '{path_expr}')"
                        )
                    if conditions:
                        where_clauses.append(f"({' OR '.join(conditions)})")
                elif isinstance(value, str):
                    # Single value (backward compatibility)
                    path_expr = f'$.{key}[*].code ? (@ == "{value}")'
                    where_clauses.append(
                        f"jsonb_path_exists(sys_taxonomies, '{path_expr}')"
                    )
            elif key in filter_map:
                col = filter_map[key]
                where_clauses.append(f"{col} = %s")
                params.append(value)

        return where_clauses, params

    def _get_paginated_documents_impl(
        self,
        page: int,
        page_size: int,
        filters: Dict[str, Any],
        filter_map: Dict[str, str],
        sort_by: str,
        sort_order: str,
    ) -> Dict[str, Any]:

        where_clauses, params = self._build_filter_clauses(filters, filter_map)

        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql

        # Sort mapping
        sort_col = "map_published_year"  # Default
        if sort_by == "year":
            sort_col = "map_published_year"
        elif sort_by == "title":
            sort_col = "map_title"
        elif sort_by == "last_updated":
            # Convert sys_last_updated (epoch) to timestamp, fallback
            sort_col = (
                "COALESCE(to_timestamp(sys_last_updated), "
                "sys_status_timestamp, '1970-01-01'::timestamp)"
            )
        elif sort_by in ("sdg", "cross_cutting_theme"):
            # Sort by first taxonomy code in the array
            # Extract first element's code from JSONB array: sys_taxonomies->'sdg'->0->'code'
            sort_col = f"COALESCE(sys_taxonomies->'{sort_by}'->0->>'code', 'zzz')"
        else:
            # Default for unknown fields
            sort_col = "map_published_year"

        # Handle sort order
        order_direction = "DESC" if sort_order.lower() == "desc" else "ASC"

        # Count query
        count_query = f"SELECT COUNT(*) FROM {self.docs_table} {where_sql}"

        # Data query
        offset = (page - 1) * page_size
        query = f"""
            SELECT
                doc_id,
                src_doc_raw_metadata,
                sys_summary,
                sys_full_summary,
                sys_taxonomies,
                sys_status,
                sys_status_timestamp,
                sys_data,
                sys_file_format,
                sys_file_size_mb,
                sys_page_count,
                sys_language,
                sys_stages,
                sys_last_updated,
                sys_error_message,
                map_title,
                map_organization,
                map_published_year,
                map_document_type,
                map_country,
                map_language,
                map_region,
                map_theme,
                map_pdf_url,
                map_report_url
            FROM {self.docs_table}
            {where_sql}
            ORDER BY {sort_col} {order_direction}
            LIMIT %s OFFSET %s
        """

        total = 0
        documents = []

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                # Get total count
                cur.execute(count_query, params)
                total = cur.fetchone()[0]

                # Get page data
                cur.execute(query, params + [page_size, offset])
                rows = cur.fetchall()

                for row in rows:
                    (
                        doc_id,
                        src_doc_raw_metadata,
                        sys_summary,
                        sys_full_summary,
                        sys_taxonomies,
                        sys_status,
                        sys_status_timestamp,
                        sys_data,
                        sys_file_format,
                        sys_file_size_mb,
                        sys_page_count,
                        sys_language,
                        sys_stages,
                        sys_last_updated,
                        sys_error_message,
                        map_title,
                        map_organization,
                        map_published_year,
                        map_document_type,
                        map_country,
                        map_language,
                        map_region,
                        map_theme,
                        map_pdf_url,
                        map_report_url,
                    ) = row

                    sys_toc = None
                    sys_toc_classified = None
                    if isinstance(sys_data, dict):
                        sys_toc = sys_data.get("sys_toc")
                        sys_toc_classified = sys_data.get("sys_toc_classified")

                    documents.append(
                        {
                            "id": doc_id,
                            "doc_id": doc_id,
                            "src_doc_raw_metadata": src_doc_raw_metadata,
                            "sys_summary": sys_summary,
                            "sys_full_summary": sys_full_summary,
                            "sys_taxonomies": sys_taxonomies,
                            "sys_status": sys_status,
                            "sys_status_timestamp": sys_status_timestamp,
                            "sys_data": sys_data,
                            "sys_file_format": sys_file_format,
                            "sys_file_size_mb": sys_file_size_mb,
                            "sys_page_count": sys_page_count,
                            "sys_language": sys_language,
                            "sys_stages": sys_stages,
                            "sys_last_updated": sys_last_updated,
                            "sys_error_message": sys_error_message,
                            "sys_toc": sys_toc,
                            "sys_toc_classified": sys_toc_classified,
                            "map_title": map_title,
                            "map_organization": map_organization,
                            "map_published_year": map_published_year,
                            "map_document_type": map_document_type,
                            "map_country": map_country,
                            "map_language": map_language,
                            "map_region": map_region,
                            "map_theme": map_theme,
                            "map_pdf_url": map_pdf_url,
                            "map_report_url": map_report_url,
                        }
                    )

        total_pages = (total + page_size - 1) // page_size

        return {
            "documents": documents,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
