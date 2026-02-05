"""Base helpers for Postgres sidecar client."""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from psycopg2.pool import SimpleConnectionPool

logger = logging.getLogger(__name__)


def build_postgres_dsn() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    if os.path.exists("/.dockerenv") and host in {"localhost", "127.0.0.1"}:
        host = "postgres"
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DBNAME") or os.getenv("POSTGRES_DB", "evidencelab")
    user = os.getenv("POSTGRES_USER", "evidencelab")
    password = os.getenv("POSTGRES_PASSWORD", "evidencelab")
    return f"dbname={db} user={user} password={password} host={host} port={port}"


class PostgresClientBase:
    """Base connection and helpers for Postgres sidecar."""

    _ALLOWED_MAP_FIELDS: set[str]
    _ALLOWED_SYS_FIELDS: set[str]

    def __init__(self, data_source: Optional[str] = None):
        source = (data_source or "uneg").lower().replace(" ", "_")
        self.data_source = source
        self.docs_table = f"docs_{source}"
        self.chunks_table = f"chunks_{source}"
        self._pool: Optional[SimpleConnectionPool] = None
        self._ensured_doc_sys_columns: set[str] = set()
        self._ensured_chunk_sys_columns: set[str] = set()

    def _get_pool(self) -> SimpleConnectionPool:
        if self._pool is None:
            self._pool = SimpleConnectionPool(
                minconn=1, maxconn=5, dsn=build_postgres_dsn()
            )
        return self._pool

    @contextlib.contextmanager
    def _get_conn(self):
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            yield conn
        finally:
            pool.putconn(conn)

    def _normalize_timestamp(
        self, value: Optional[datetime | str]
    ) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _extract_status_timestamp(
        self, sys_fields: Dict[str, Any]
    ) -> Optional[datetime]:
        stages = sys_fields.get("sys_stages")
        if not isinstance(stages, dict):
            return None
        latest = None
        for stage in stages.values():
            if not isinstance(stage, dict):
                continue
            stage_time = stage.get("at")
            if not isinstance(stage_time, str):
                continue
            parsed = self._normalize_timestamp(stage_time)
            if parsed is None:
                continue
            if latest is None or parsed > latest:
                latest = parsed
        return latest
