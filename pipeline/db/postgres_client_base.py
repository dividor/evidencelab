"""Base helpers for Postgres sidecar client."""

from __future__ import annotations

import contextlib
import logging
import math
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional

import psycopg2
from psycopg2.pool import PoolError, ThreadedConnectionPool

from pipeline.db.config import resolve_data_source

logger = logging.getLogger(__name__)


class PostgresPoolTimeout(PoolError):
    """No pooled connection came free within ``POSTGRES_POOL_TIMEOUT`` seconds.

    The database is busier than the pool can serve. A subclass of psycopg2's
    ``PoolError``, so code that already handles pool errors still does.
    """


class QueueingConnectionPool(ThreadedConnectionPool):
    """A thread-safe pool where a caller waits for a connection when all are in use.

    psycopg2's own pools raise ``PoolError("connection pool exhausted")`` the
    moment ``maxconn`` connections are checked out. One search page asks for
    its filter counts and a page of document thumbnails at once, each request
    on its own thread: measured on an AWS deployment, that was more than the
    default 16 connections, so the filter list and six thumbnails failed even
    though every query takes milliseconds.

    Here a caller waits until another returns a connection, as SQLAlchemy's
    pool does. The wait is bounded: after ``timeout`` seconds it raises
    ``PostgresPoolTimeout``. The pool still never opens more than ``maxconn``
    connections, so the load on the database server is unchanged.

    A semaphore counts the free places. ``getconn`` takes one before asking
    the parent pool, so the parent never sees more than ``maxconn`` callers
    and never raises "exhausted"; ``putconn`` gives the place back once the
    parent has taken the connection back. Keyed connections are refused: a
    second ``getconn`` with the same key returns the same connection, which
    would take a place it never gives back.
    """

    def __init__(
        self, minconn: int, maxconn: int, *args: Any, timeout: float, **kwargs: Any
    ):
        if not (math.isfinite(timeout) and timeout > 0):
            raise ValueError(f"timeout must be a number of seconds > 0, got {timeout}")
        super().__init__(minconn, maxconn, *args, **kwargs)
        self.timeout = timeout
        self._free_places = threading.BoundedSemaphore(maxconn)

    def getconn(self, key: Any = None) -> Any:
        if key is not None:
            raise ValueError(
                "QueueingConnectionPool does not hand out keyed connections"
            )
        if not self._free_places.acquire(timeout=self.timeout):
            raise PostgresPoolTimeout(
                f"no Postgres connection came free within {self.timeout:g}s "
                f"(all {self.maxconn} in use)"
            )
        try:
            return super().getconn()
        except BaseException:
            self._free_places.release()
            raise

    def putconn(self, conn: Any = None, key: Any = None, close: bool = False) -> None:
        if key is not None:
            raise ValueError(
                "QueueingConnectionPool does not hand out keyed connections"
            )
        # The parent raises PoolError for a connection it didn't hand out, so a
        # place is only given back for a connection that came from this pool.
        try:
            super().putconn(conn, close=close)
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # psycopg2 rolls back a connection returned mid-transaction. If
            # that fails the connection is broken, and psycopg2 raised before
            # marking it returned, so its place would be lost for good. Close
            # it and drop it instead.
            logger.warning("Closed a broken Postgres connection on return")
            super().putconn(conn, close=True)
        self._free_places.release()


def build_postgres_dsn() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    if os.path.exists("/.dockerenv") and host in {"localhost", "127.0.0.1"}:
        host = "postgres"
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DBNAME") or os.getenv("POSTGRES_DB", "evidencelab")
    user = os.getenv("POSTGRES_USER", "evidencelab")
    password = os.getenv("POSTGRES_PASSWORD", "evidencelab")
    return f"dbname={db} user={user} password={password} host={host} port={port}"


def _pool_bounds() -> tuple[int, int]:
    """Connection-pool size, from the environment.

    These bound one pool, and there is exactly one pool per process per data
    source (see ``_POOL_REGISTRY``), so ``maxconn`` caps how many queries this
    process can run against one data source at once. Past it, a caller waits
    for a connection to come free (see ``QueueingConnectionPool``).
    ``minconn`` is how many connections are kept open when returned: psycopg2
    closes anything beyond it, so a low value means a fresh connect per
    request under load.

    Sizing note: the process-wide floor is ``minconn`` x (data sources in use),
    and the ceiling ``maxconn`` x (data sources in use). Keep that under the
    server's ``max_connections`` once every process that talks to it is counted
    -- a ``--workers N`` pipeline run is N+1 processes.
    """
    maxconn = int(os.getenv("POSTGRES_POOL_MAX", "16"))
    minconn = int(os.getenv("POSTGRES_POOL_MIN", "4"))
    if maxconn < 1:
        raise ValueError(f"POSTGRES_POOL_MAX must be >= 1, got {maxconn}")
    if not 0 <= minconn <= maxconn:
        raise ValueError(
            f"POSTGRES_POOL_MIN must be between 0 and POSTGRES_POOL_MAX "
            f"({maxconn}), got {minconn}"
        )
    return minconn, maxconn


def _pool_timeout() -> float:
    """Seconds a caller waits for a free connection, from ``POSTGRES_POOL_TIMEOUT``."""
    raw = os.getenv("POSTGRES_POOL_TIMEOUT", "30")
    message = f"POSTGRES_POOL_TIMEOUT must be a number of seconds > 0, got {raw!r}"
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise ValueError(message) from exc
    if not (math.isfinite(timeout) and timeout > 0):
        raise ValueError(message)
    return timeout


# One pool per (process, data source). A pool is a set of connections to a
# database, so it belongs to the process rather than to a client instance.
#
# ``PostgresClient`` is constructed in six places that are all live inside a
# single pipeline worker (``db/database.py``, ``processors/indexing/indexer.py``,
# ``processors/tagging/tagger_processor.py``, ``tagger_taxonomy.py``,
# ``tagger_section_type.py``, ``processors/scanning/scanner.py``). When each
# instance built its own pool, ``ThreadedConnectionPool`` opened ``minconn``
# connections per pool, so the idle floor was ``6 x POSTGRES_POOL_MIN`` per
# process. Measured with the shipped defaults and ``--workers 7``: 64-68 idle
# connections from the pipeline alone, which exhausted a stock
# ``max_connections=100`` server and failed documents.
#
# The pid is part of the key so that a forked child -- Celery's default worker
# pool is prefork -- builds its own pool instead of operating on connection
# sockets inherited from its parent, which would corrupt both sides. The
# pipeline's own workers use the "spawn" start method, so they begin with an
# empty registry either way.
_POOL_REGISTRY: Dict[tuple[int, str, str], QueueingConnectionPool] = {}
_POOL_REGISTRY_LOCK = threading.Lock()


def get_shared_pool(data_source: str) -> QueueingConnectionPool:
    """Return this process's pool for ``data_source``, building it once."""
    dsn = build_postgres_dsn()
    key = (os.getpid(), data_source, dsn)
    pool = _POOL_REGISTRY.get(key)
    if pool is not None:
        return pool
    # Double-checked locking: the client is shared across every request thread,
    # so an unguarded lazy init can build two pools and leak one.
    with _POOL_REGISTRY_LOCK:
        pool = _POOL_REGISTRY.get(key)
        if pool is None:
            minconn, maxconn = _pool_bounds()
            timeout = _pool_timeout()
            pool = QueueingConnectionPool(
                minconn=minconn, maxconn=maxconn, dsn=dsn, timeout=timeout
            )
            _POOL_REGISTRY[key] = pool
            logger.debug(
                "Opened Postgres pool for %r in pid %s (min=%s, max=%s, wait=%ss)",
                data_source,
                key[0],
                minconn,
                maxconn,
                timeout,
            )
    return pool


def checkout_live_connection(pool: QueueingConnectionPool):
    """A connection from POOL that the server still answers on.

    The server can end a pooled connection while it sits idle: a database
    restart (AWS applies minor upgrades in the maintenance window), a failover,
    or a restore that ends every session. psycopg2 only notices when a query on
    it fails, so without a check each idle connection costs one failed request
    afterwards. Each connection is pinged on checkout, as SQLAlchemy's
    ``pool_pre_ping`` does for the API's auth database; one that doesn't answer
    is closed, dropped from the pool and replaced. If no connection answers
    after the pool's maximum plus one tries, the database is down, and the last
    error is raised.
    """
    attempts = pool.maxconn + 1
    for attempt in range(1, attempts + 1):
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.rollback()
            return conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            pool.putconn(conn, close=True)
            if attempt == attempts:
                raise
            logger.warning(
                "Replaced a Postgres connection the server had closed (%d/%d)",
                attempt,
                attempts,
            )
    raise RuntimeError("unreachable: the last attempt returns or raises")


def close_all_pools() -> None:
    """Close every pool this process opened, for shutdown and test teardown."""
    with _POOL_REGISTRY_LOCK:
        for key, pool in list(_POOL_REGISTRY.items()):
            try:
                pool.closeall()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to close Postgres pool %s", key, exc_info=True)
            del _POOL_REGISTRY[key]


class PostgresClientBase:
    """Base connection and helpers for Postgres sidecar."""

    _ALLOWED_MAP_FIELDS: set[str]
    _ALLOWED_SYS_FIELDS: set[str]

    def __init__(self, data_source: Optional[str] = None):
        source = resolve_data_source(data_source).lower().replace(" ", "_")
        self.data_source = source
        self.docs_table = f"docs_{source}"
        self.chunks_table = f"chunks_{source}"
        self._ensured_doc_sys_columns: set[str] = set()
        self._ensured_doc_map_columns: set[str] = set()
        self._ensured_chunk_sys_columns: set[str] = set()

    def _get_pool(self) -> QueueingConnectionPool:
        return get_shared_pool(self.data_source)

    @contextlib.contextmanager
    def _get_conn(self):
        pool = self._get_pool()
        conn = checkout_live_connection(pool)
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
