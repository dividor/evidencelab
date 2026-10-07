"""Guards against blocking the API's single event loop.

The API runs one uvicorn worker, so an ``async def`` route that calls the
synchronous Postgres or Qdrant client holds the event loop for the whole
query and every other request in the process waits behind it. These tests
fail if such a route is (re)introduced, and cover the connection-pool sizing
that the threadpooled routes depend on.
"""

import ast
import importlib
import os
import pathlib
from unittest.mock import patch

import pytest

ROUTES_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "backend" / "routes"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# Names that reach a synchronous database or vector-store client.
SYNC_CLIENT_NAMES = {
    "get_pg_for_source",
    "get_db_for_source",
    "PostgresClient",
    "QdrantClient",
}


def _is_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for deco in fn.decorator_list:
        node = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(node, ast.Attribute) and node.attr in HTTP_METHODS:
            return True
    return False


def _referenced_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    found = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def _blocking_routes() -> list[str]:
    """Async routes that touch a sync client without handing it to a thread."""
    offenders = []
    for path in sorted(ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef) or not _is_route(fn):
                continue
            names = _referenced_names(fn)
            if (names & SYNC_CLIENT_NAMES) and "run_in_threadpool" not in names:
                offenders.append(f"{path.name}:{fn.lineno} {fn.name}")
    return offenders


@pytest.mark.unit
def test_routes_when_using_sync_clients_then_never_block_the_event_loop():
    offenders = _blocking_routes()
    assert offenders == [], (
        "These async routes call a synchronous Postgres/Qdrant client inline, "
        "which holds the single event loop and stalls every other request. "
        "Either hand the work to run_in_threadpool(), or declare the route "
        "with a plain `def` so FastAPI runs it in the threadpool:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.unit
def test_guard_when_a_blocking_route_exists_then_it_is_detected():
    """The guard above is only meaningful if it can actually fail."""
    source = (
        "@router.get('/x')\n"
        "async def handler():\n"
        "    pg = get_pg_for_source('uneg')\n"
        "    return pg.fetch_docs(['a'])\n"
    )
    tree = ast.parse(source)
    fn = tree.body[0]
    assert _is_route(fn)
    names = _referenced_names(fn)
    assert names & SYNC_CLIENT_NAMES
    assert "run_in_threadpool" not in names


class TestPoolBounds:
    """Connection-pool sizing for the synchronous Postgres client."""

    @staticmethod
    def _reload():
        import pipeline.db.postgres_client_base as base

        return importlib.reload(base)

    @pytest.mark.unit
    def test_pool_bounds_when_unset_then_defaults_allow_concurrency(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POSTGRES_POOL_MIN", None)
            os.environ.pop("POSTGRES_POOL_MAX", None)
            base = self._reload()
            minconn, maxconn = base._pool_bounds()
        # The old hard-coded pool was minconn=1/maxconn=5, which both capped
        # concurrency and closed every returned connection beyond the first.
        assert maxconn > 5
        assert minconn > 1
        assert minconn <= maxconn

    @pytest.mark.unit
    def test_pool_bounds_when_env_set_then_env_wins(self):
        with patch.dict(
            os.environ, {"POSTGRES_POOL_MIN": "3", "POSTGRES_POOL_MAX": "9"}
        ):
            base = self._reload()
            assert base._pool_bounds() == (3, 9)

    @pytest.mark.unit
    def test_pool_bounds_when_min_exceeds_max_then_raises(self):
        with patch.dict(
            os.environ, {"POSTGRES_POOL_MIN": "10", "POSTGRES_POOL_MAX": "4"}
        ):
            base = self._reload()
            with pytest.raises(ValueError, match="POSTGRES_POOL_MIN"):
                base._pool_bounds()

    @pytest.mark.unit
    def test_pool_bounds_when_max_below_one_then_raises(self):
        with patch.dict(os.environ, {"POSTGRES_POOL_MAX": "0"}):
            base = self._reload()
            with pytest.raises(ValueError, match="POSTGRES_POOL_MAX"):
                base._pool_bounds()

    @pytest.mark.unit
    def test_client_when_shared_across_threads_then_pool_is_thread_safe(self):
        """psycopg2's SimpleConnectionPool is documented as not shareable."""
        from psycopg2.pool import ThreadedConnectionPool

        import pipeline.db.postgres_client_base as base

        source = pathlib.Path(base.__file__).read_text()
        assert "SimpleConnectionPool" not in source
        assert ThreadedConnectionPool.__name__ in source
