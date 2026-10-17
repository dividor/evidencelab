"""A Postgres pool belongs to the process, not to a client instance.

``PostgresClient`` is constructed in six places that are all live inside one
pipeline worker. When each instance built its own pool, every pool opened
``POSTGRES_POOL_MIN`` connections, so the process-wide idle floor was six times
the configured minimum. Measured with the shipped defaults and ``--workers 7``:
64-68 idle connections from the pipeline alone, which exhausted a stock
``max_connections=100`` server and failed documents mid-run.

These tests exercise the real registry in ``postgres_client_base``.
"""

import threading
from typing import Any, Dict, List

import pytest

import pipeline.db.postgres_client_base as base

pytestmark = pytest.mark.unit

# The six live construction sites, as of this change.
CONSTRUCTION_SITES = 6


class _FakePool:
    """Stands in for ThreadedConnectionPool, counting what it would open."""

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        self.minconn = kwargs.get("minconn")
        self.closed = False
        BUILT.append(self)

    def closeall(self) -> None:
        self.closed = True


BUILT: List[_FakePool] = []


@pytest.fixture(autouse=True)
def _isolate_registry(monkeypatch):
    """Each test gets an empty registry and a fake pool class."""
    BUILT.clear()
    monkeypatch.setattr(base, "ThreadedConnectionPool", _FakePool)
    saved: Dict[Any, Any] = dict(base._POOL_REGISTRY)
    base._POOL_REGISTRY.clear()
    yield
    base._POOL_REGISTRY.clear()
    base._POOL_REGISTRY.update(saved)


def _opened_connections() -> int:
    """Connections the built pools would hold open at idle."""
    return sum(p.minconn or 0 for p in BUILT)


class TestPoolSharing:
    def test_same_data_source_shares_one_pool(self):
        a = base.PostgresClientBase("uneg")
        b = base.PostgresClientBase("uneg")
        assert a._get_pool() is b._get_pool()
        assert len(BUILT) == 1

    def test_different_data_sources_get_their_own_pool(self):
        a = base.PostgresClientBase("uneg")
        b = base.PostgresClientBase("worldbank")
        assert a._get_pool() is not b._get_pool()
        assert len(BUILT) == 2

    def test_data_source_name_is_normalised_before_keying(self):
        """'UN Eg' and 'un_eg' are the same source, so one pool."""
        a = base.PostgresClientBase("UN Eg")
        b = base.PostgresClientBase("un_eg")
        assert a._get_pool() is b._get_pool()
        assert len(BUILT) == 1

    def test_six_construction_sites_open_one_pool_not_six(self, monkeypatch):
        """The regression this change exists for."""
        monkeypatch.setenv("POSTGRES_POOL_MIN", "4")
        monkeypatch.setenv("POSTGRES_POOL_MAX", "16")
        clients = [base.PostgresClientBase("uneg") for _ in range(CONSTRUCTION_SITES)]
        for client in clients:
            client._get_pool()
        assert len(BUILT) == 1, (
            f"{len(BUILT)} pools for one data source in one process; each opens "
            f"its own POSTGRES_POOL_MIN connections."
        )
        assert _opened_connections() == 4, (
            f"idle floor is {_opened_connections()} connections for one data "
            f"source; before this change six instances held 6 x 4 = 24."
        )

    def test_repeated_lookups_do_not_grow_the_registry(self):
        client = base.PostgresClientBase("uneg")
        for _ in range(50):
            client._get_pool()
        assert len(BUILT) == 1
        assert len(base._POOL_REGISTRY) == 1

    def test_concurrent_first_use_builds_exactly_one_pool(self):
        """Many API request threads can arrive before the pool exists."""
        clients = [base.PostgresClientBase("uneg") for _ in range(8)]
        barrier = threading.Barrier(8)

        def race(client):
            barrier.wait()
            client._get_pool()

        threads = [threading.Thread(target=race, args=(c,)) for c in clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(BUILT) == 1, f"{len(BUILT)} pools built by 8 concurrent threads"


class TestForkSafety:
    def test_forked_child_does_not_reuse_the_parent_pool(self, monkeypatch):
        """Celery's default worker pool forks; inherited sockets would corrupt."""
        parent = base.PostgresClientBase("uneg")
        parent_pool = parent._get_pool()

        real_pid = base.os.getpid()
        monkeypatch.setattr(base.os, "getpid", lambda: real_pid + 1)
        child_pool = base.PostgresClientBase("uneg")._get_pool()

        assert child_pool is not parent_pool
        assert len(BUILT) == 2


class TestCloseAllPools:
    def test_closes_and_clears_every_pool(self):
        base.PostgresClientBase("uneg")._get_pool()
        base.PostgresClientBase("worldbank")._get_pool()
        assert len(base._POOL_REGISTRY) == 2

        base.close_all_pools()

        assert base._POOL_REGISTRY == {}
        assert all(p.closed for p in BUILT)

    def test_a_pool_that_fails_to_close_is_still_removed(self):
        class _Angry(_FakePool):
            def closeall(self):
                raise RuntimeError("connection already gone")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(base, "ThreadedConnectionPool", _Angry)
            base.PostgresClientBase("uneg")._get_pool()
            base.close_all_pools()

        assert base._POOL_REGISTRY == {}, "a failed close must not wedge the registry"

    def test_pool_is_rebuilt_after_close(self):
        client = base.PostgresClientBase("uneg")
        first = client._get_pool()
        base.close_all_pools()
        second = client._get_pool()
        assert second is not first
        assert len(BUILT) == 2


class TestPoolBounds:
    def test_bounds_are_passed_through_to_the_pool(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_POOL_MIN", "2")
        monkeypatch.setenv("POSTGRES_POOL_MAX", "7")
        base.PostgresClientBase("uneg")._get_pool()
        assert BUILT[0].kwargs["minconn"] == 2
        assert BUILT[0].kwargs["maxconn"] == 7

    def test_invalid_bounds_still_raise(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_POOL_MIN", "9")
        monkeypatch.setenv("POSTGRES_POOL_MAX", "2")
        with pytest.raises(ValueError):
            base.PostgresClientBase("uneg")._get_pool()
