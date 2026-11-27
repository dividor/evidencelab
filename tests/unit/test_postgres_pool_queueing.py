"""When every pooled connection is in use, a caller waits for one instead of failing.

psycopg2's pools raise ``PoolError("connection pool exhausted")`` as soon as
``maxconn`` connections are checked out. On an AWS deployment one search page
asked for its filter counts and a page of thumbnails at once, more than the
default 16 connections, so the filter list and six thumbnails failed with 500
errors although each query takes milliseconds. ``QueueingConnectionPool``
makes the caller wait, for at most ``POSTGRES_POOL_TIMEOUT`` seconds, and never
opens more than ``maxconn`` connections.

These tests run the real pool. Only ``psycopg2.connect`` is replaced, by a
stand-in that counts the connections it opens.
"""

import math
import threading
import time
from typing import List

import psycopg2
import psycopg2.extensions
import pytest
from psycopg2.pool import PoolError, ThreadedConnectionPool

import pipeline.db.postgres_client_base as base

pytestmark = pytest.mark.unit


class _Info:
    transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE


class _Conn:
    """The parts of a psycopg2 connection the pool touches."""

    def __init__(self, number: int):
        self.number = number
        self.closed = 0
        self.info = _Info()

    def close(self) -> None:
        self.closed = 1

    def rollback(self) -> None:
        pass


class _Server:
    """Stands in for psycopg2.connect, counting the connections opened."""

    def __init__(self) -> None:
        self.opened: List[_Conn] = []
        self.most_open_at_once = 0
        self.fail_next = 0
        self._lock = threading.Lock()

    def connect(self, *args, **kwargs) -> _Conn:
        with self._lock:
            if self.fail_next:
                self.fail_next -= 1
                raise psycopg2.OperationalError("could not connect to server")
            conn = _Conn(len(self.opened))
            self.opened.append(conn)
            self.most_open_at_once = max(self.most_open_at_once, self.open_now())
            return conn

    def open_now(self) -> int:
        return sum(1 for c in self.opened if not c.closed)


@pytest.fixture
def server(monkeypatch) -> _Server:
    srv = _Server()
    monkeypatch.setattr(psycopg2, "connect", srv.connect)
    return srv


def _pool(maxconn: int, timeout: float = 5.0, minconn: int = 0):
    return base.QueueingConnectionPool(
        minconn=minconn, maxconn=maxconn, dsn="dbname=test", timeout=timeout
    )


def _burst(pool, requests: int, hold_seconds: float) -> List[Exception]:
    """REQUESTS threads at once, each holding a connection for HOLD_SECONDS."""
    errors: List[Exception] = []
    start = threading.Barrier(requests)

    def request() -> None:
        start.wait()
        try:
            conn = pool.getconn()
        except Exception as exc:  # the test records every failure
            errors.append(exc)
            return
        time.sleep(hold_seconds)
        pool.putconn(conn)

    threads = [threading.Thread(target=request) for _ in range(requests)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


class TestQueueingConnectionPool:
    def test_burst_when_larger_than_pool_then_every_request_gets_a_connection(
        self, server
    ):
        pool = _pool(maxconn=4)
        errors = _burst(pool, requests=40, hold_seconds=0.01)
        assert errors == []
        assert server.most_open_at_once <= 4, (
            f"The pool had {server.most_open_at_once} connections open at once "
            f"during a burst of 40; it must never hold more than maxconn (4)."
        )

    def test_plain_psycopg2_pool_when_same_burst_then_fails(self, server):
        """Self-check: the burst above really is more than psycopg2's pool takes."""
        pool = ThreadedConnectionPool(minconn=0, maxconn=4, dsn="dbname=test")
        errors = _burst(pool, requests=40, hold_seconds=0.01)
        assert (
            errors
        ), "the burst no longer exhausts a plain pool; the test proves nothing"
        assert all("exhausted" in str(e) for e in errors)

    def test_getconn_when_all_in_use_then_waits_for_a_returned_connection(self, server):
        # minconn=1 so the returned connection is kept rather than closed.
        pool = _pool(maxconn=1, minconn=1)
        held = pool.getconn()
        got: List[_Conn] = []
        waited: List[float] = []

        def wait_for_one() -> None:
            t0 = time.monotonic()
            got.append(pool.getconn())
            waited.append(time.monotonic() - t0)

        waiter = threading.Thread(target=wait_for_one)
        waiter.start()
        time.sleep(0.2)
        assert got == [], "the second caller must wait while the only connection is out"
        pool.putconn(held)
        waiter.join(timeout=5)
        assert got == [held], "the waiting caller gets the returned connection"
        assert waited[0] >= 0.15

    def test_getconn_when_nothing_returned_within_timeout_then_raises(self, server):
        pool = _pool(maxconn=1, timeout=0.2)
        pool.getconn()
        t0 = time.monotonic()
        with pytest.raises(base.PostgresPoolTimeout, match="within 0.2s") as caught:
            pool.getconn()
        assert time.monotonic() - t0 >= 0.15
        assert isinstance(
            caught.value, PoolError
        ), "code that already handles psycopg2's PoolError must still catch it"

    def test_putconn_when_closing_a_dead_connection_then_its_place_is_free(
        self, server
    ):
        """checkout_live_connection closes a connection the server ended."""
        pool = _pool(maxconn=1, timeout=0.2)
        dead = pool.getconn()
        pool.putconn(dead, close=True)
        assert dead.closed
        assert pool.getconn() is not dead

    def test_getconn_when_connect_fails_then_its_place_is_given_back(self, server):
        pool = _pool(maxconn=1, timeout=0.2)
        server.fail_next = 1
        with pytest.raises(psycopg2.OperationalError):
            pool.getconn()
        # With the place leaked, this would time out.
        assert isinstance(pool.getconn(), _Conn)

    def test_putconn_when_connection_is_not_from_pool_then_no_place_is_added(
        self, server
    ):
        pool = _pool(maxconn=1, timeout=0.2)
        pool.getconn()
        with pytest.raises(PoolError, match="unkeyed"):
            pool.putconn(_Conn(99))
        # A wrongly added place would let a second connection out.
        with pytest.raises(base.PostgresPoolTimeout):
            pool.getconn()

    def test_putconn_when_rollback_of_a_broken_connection_fails_then_place_is_kept(
        self, server, caplog
    ):
        """psycopg2 rolls back a connection returned mid-transaction."""
        pool = _pool(maxconn=1, timeout=0.2, minconn=1)
        conn = pool.getconn()

        class _InError:
            transaction_status = psycopg2.extensions.TRANSACTION_STATUS_INERROR

        def broken_rollback() -> None:
            raise psycopg2.OperationalError("server closed the connection")

        conn.info = _InError()
        conn.rollback = broken_rollback
        pool.putconn(conn)
        assert conn.closed, "the broken connection is closed, not kept"
        assert "broken Postgres connection" in caplog.text
        assert pool.getconn() is not conn, "its place came back for a new one"

    def test_putconn_when_returned_twice_then_raises(self, server):
        pool = _pool(maxconn=1)
        conn = pool.getconn()
        pool.putconn(conn)
        with pytest.raises(PoolError):
            pool.putconn(conn)

    def test_keyed_connections_when_requested_then_refused(self, server):
        pool = _pool(maxconn=2)
        with pytest.raises(ValueError, match="keyed"):
            pool.getconn("k")
        conn = pool.getconn()
        with pytest.raises(ValueError, match="keyed"):
            pool.putconn(conn, key="k")

    @pytest.mark.parametrize("timeout", [0, -1, math.inf, math.nan])
    def test_timeout_when_not_a_positive_number_then_refused(self, server, timeout):
        with pytest.raises(ValueError, match="timeout"):
            _pool(maxconn=1, timeout=timeout)


class TestPoolTimeoutSetting:
    def test_timeout_when_unset_then_default(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_POOL_TIMEOUT", raising=False)
        assert base._pool_timeout() == 30.0, "the default .env.example documents"

    def test_timeout_when_set_then_used(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_POOL_TIMEOUT", "2.5")
        assert base._pool_timeout() == 2.5

    @pytest.mark.parametrize("raw", ["0", "-3", "inf", "nan", "soon", ""])
    def test_timeout_when_invalid_then_fails_naming_the_setting(self, monkeypatch, raw):
        monkeypatch.setenv("POSTGRES_POOL_TIMEOUT", raw)
        with pytest.raises(ValueError, match="POSTGRES_POOL_TIMEOUT"):
            base._pool_timeout()

    def test_shared_pool_when_built_then_uses_the_setting(self, monkeypatch, server):
        monkeypatch.setenv("POSTGRES_POOL_TIMEOUT", "7")
        monkeypatch.setenv("POSTGRES_POOL_MIN", "0")
        monkeypatch.setenv("POSTGRES_POOL_MAX", "3")
        monkeypatch.setattr(base, "_POOL_REGISTRY", {})
        pool = base.get_shared_pool("queueing_test")
        assert isinstance(pool, base.QueueingConnectionPool)
        assert (pool.timeout, pool.maxconn) == (7.0, 3)
        base.close_all_pools()
