"""A pooled Postgres connection is checked before use, and replaced if the server closed it.

The server ends idle pooled connections on a restart, a failover or a restore
that ends every session. Before this check, psycopg2's pool handed them out
anyway: measured against a real Postgres 16, after the server ended the pool's
4 idle connections the next 4 requests failed with "server closed the
connection unexpectedly"; on an AWS deployment, search and the filter lists
failed the same way after a restore until the API restarted.
"""

import logging
from typing import List

import psycopg2
import pytest

import pipeline.db.postgres_client_base as base

pytestmark = pytest.mark.unit


class _Cursor:
    def __init__(self, conn: "_Conn"):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str) -> None:
        self.conn.executed.append(sql)
        if self.conn.dead:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")


class _Conn:
    def __init__(self, name: str, dead: bool = False, closed: bool = False):
        self.name = name
        self.dead = dead
        self.closed = closed
        self.executed: List[str] = []
        self.rolled_back = False

    def cursor(self):
        if self.closed:
            raise psycopg2.InterfaceError("connection already closed")
        return _Cursor(self)

    def rollback(self) -> None:
        self.rolled_back = True


class _Pool:
    """Hands out CONNS in order, recording what comes back and how."""

    def __init__(self, conns: List[_Conn], maxconn: int = 3):
        self._conns = list(conns)
        self.maxconn = maxconn
        self.returned: List[tuple] = []

    def getconn(self):
        return self._conns.pop(0)

    def putconn(self, conn, close: bool = False) -> None:
        self.returned.append((conn.name, close))


class TestCheckoutLiveConnection:
    def test_checkout_when_connection_answers_then_returned_after_ping(self):
        live = _Conn("a")
        pool = _Pool([live])
        assert base.checkout_live_connection(pool) is live
        assert live.executed == ["SELECT 1"]
        assert live.rolled_back
        assert pool.returned == []

    def test_checkout_when_server_closed_connection_then_replaced(self, caplog):
        pool = _Pool([_Conn("dead", dead=True), _Conn("live")])
        with caplog.at_level(logging.WARNING, logger=base.__name__):
            conn = base.checkout_live_connection(pool)
        assert conn.name == "live"
        assert pool.returned == [("dead", True)]
        assert (
            "Replaced a Postgres connection the server had closed (1/4)" in caplog.text
        )

    def test_checkout_when_connection_already_closed_then_replaced(self):
        pool = _Pool([_Conn("closed", closed=True), _Conn("live")])
        assert base.checkout_live_connection(pool).name == "live"
        assert pool.returned == [("closed", True)]

    def test_checkout_when_every_idle_connection_dead_then_all_replaced(self):
        dead = [_Conn(f"dead{i}", dead=True) for i in range(3)]
        pool = _Pool(dead + [_Conn("live")], maxconn=3)
        assert base.checkout_live_connection(pool).name == "live"
        assert pool.returned == [("dead0", True), ("dead1", True), ("dead2", True)]

    def test_checkout_when_database_down_then_last_error_raised(self):
        pool = _Pool([_Conn(f"dead{i}", dead=True) for i in range(4)], maxconn=3)
        with pytest.raises(psycopg2.OperationalError, match="server closed"):
            base.checkout_live_connection(pool)
        assert len(pool.returned) == 4
        assert all(close for _, close in pool.returned)


class TestGetConn:
    def test_get_conn_when_used_then_checked_connection_returned_to_pool(
        self, monkeypatch
    ):
        pool = _Pool([_Conn("dead", dead=True), _Conn("live")])
        client = base.PostgresClientBase("wfp")
        monkeypatch.setattr(client, "_get_pool", lambda: pool)
        with client._get_conn() as conn:
            assert conn.name == "live"
        assert pool.returned == [("dead", True), ("live", False)]
