"""Stats helpers for Postgres sidecar."""

from __future__ import annotations

from typing import Any, Dict, Tuple


class PostgresStatsMixin:
    """Stats queries for Postgres sidecar tables."""

    docs_table: str
    _ALLOWED_MAP_FIELDS: set[str]
    _ALLOWED_SYS_FIELDS: set[str]

    def _get_conn(self):
        raise NotImplementedError

    def _validate_field_name(self, field: str, from_sys_data: bool) -> None:
        if from_sys_data and field not in self._ALLOWED_SYS_FIELDS:
            raise ValueError(f"Invalid sys field for stats: {field}")
        if not from_sys_data and field not in self._ALLOWED_MAP_FIELDS:
            raise ValueError(f"Invalid map field for stats: {field}")

    def fetch_status_counts(self) -> Dict[str, int]:
        query = f"""
            SELECT sys_status AS status, COUNT(*) AS count
            FROM {self.docs_table}
            GROUP BY status
        """
        results: Dict[str, int] = {}
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                for status, count in cur.fetchall():
                    if not status:
                        continue
                    results[str(status)] = int(count or 0)
        return results

    def fetch_field_counts(
        self, field: str, *, from_sys_data: bool = False
    ) -> Dict[str, int]:
        self._validate_field_name(field, from_sys_data)
        params: Tuple[Any, ...]
        if from_sys_data:
            query = f"""
                SELECT sys_data ->> %s AS field_value, COUNT(*) AS count
                FROM {self.docs_table}
                GROUP BY field_value
            """
            params = (field,)
        else:
            query = f"""
                SELECT {field} AS field_value, COUNT(*) AS count
                FROM {self.docs_table}
                GROUP BY field_value
            """
            params = ()
        results: Dict[str, int] = {}
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                for field_value, count in cur.fetchall():
                    if field_value is None:
                        continue
                    results[str(field_value)] = int(count or 0)
        return results

    def fetch_field_status_breakdown(
        self, field: str, *, from_sys_data: bool = False
    ) -> Dict[str, Dict[str, int]]:
        self._validate_field_name(field, from_sys_data)
        params: Tuple[Any, ...]
        if from_sys_data:
            query = f"""
                SELECT
                    sys_data ->> %s AS field_value,
                    sys_status AS status,
                    COUNT(*) AS count
                FROM {self.docs_table}
                GROUP BY field_value, status
            """
            params = (field,)
        else:
            query = f"""
                SELECT
                    {field} AS field_value,
                    sys_status AS status,
                    COUNT(*) AS count
                FROM {self.docs_table}
                GROUP BY field_value, status
            """
            params = ()
        breakdown: Dict[str, Dict[str, int]] = {}
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                for field_value, status, count in cur.fetchall():
                    if field_value is None or not status:
                        continue
                    value_key = str(field_value)
                    status_key = str(status)
                    breakdown.setdefault(value_key, {})[status_key] = int(count or 0)
        return breakdown
