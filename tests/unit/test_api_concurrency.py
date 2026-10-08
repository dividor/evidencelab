"""Concurrency behaviour of the document routes.

The API serves every request on one event loop. A route that performs its
blocking database work on that loop serialises the whole process: a second
copy of the same request waits for the first, and unrelated lightweight
requests wait behind both. These tests drive the real routes through a
TestClient with a deliberately slow database stub and assert the opposite.

They fail if a route is moved back onto the event loop, which is the
regression they exist to catch.
"""

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ui.backend.routes import documents as documents_routes

pytestmark = pytest.mark.unit

DOC_ID = "11111111-1111-5111-8111-111111111111"
SLOW_SECONDS = 0.4


class _SlowPg:
    """Stands in for the synchronous Postgres client, and takes its time.

    Records the highest number of callers inside ``fetch_docs`` at once, which
    is what distinguishes threadpooled routes from ones holding the loop.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def fetch_docs(self, doc_ids):
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(SLOW_SECONDS)
            return {
                str(doc_ids[0]): {
                    "doc_id": str(doc_ids[0]),
                    "map_title": "A document",
                    "sys_data": {},
                }
            }
        finally:
            with self._lock:
                self._in_flight -= 1


@pytest.fixture
def client_and_pg(monkeypatch):
    pg = _SlowPg()
    monkeypatch.setattr(documents_routes, "get_pg_for_source", lambda _s=None: pg)
    monkeypatch.setattr(documents_routes, "get_db_for_source", lambda _s=None: None)
    monkeypatch.setattr(documents_routes, "is_hidden", lambda _doc: False)
    monkeypatch.setattr(documents_routes, "normalize_document_payload", lambda doc: doc)

    app = FastAPI()
    app.include_router(documents_routes.router)

    @app.get("/probe")
    async def probe():
        """A trivial async route: it only waits if the event loop is held."""
        return {"ok": True}

    with TestClient(app) as client:
        yield client, pg


def _get_document(client, results):
    response = client.get(f"/document/{DOC_ID}", params={"data_source": "uneg"})
    results.append(response.status_code)


def test_document_route_when_called_concurrently_then_requests_overlap(
    client_and_pg,
):
    client, pg = client_and_pg
    results: list[int] = []
    threads = [
        threading.Thread(target=_get_document, args=(client, results)) for _ in range(3)
    ]

    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started

    assert results == [200, 200, 200]
    assert pg.max_in_flight > 1, (
        "Concurrent requests to /document never overlapped in the database "
        "call, so the route is running on the event loop. Declare it `def`, "
        "or hand its blocking section to run_in_threadpool()."
    )
    # Serialised, three 0.4s requests would take ~1.2s.
    assert elapsed < SLOW_SECONDS * 2.5, (
        f"Three concurrent requests took {elapsed:.2f}s; serialised they "
        f"would take about {SLOW_SECONDS * 3:.2f}s."
    )


def test_probe_route_when_a_slow_document_request_is_in_flight_then_stays_fast(
    client_and_pg,
):
    """The head-of-line blocking this change exists to remove."""
    client, _pg = client_and_pg
    results: list[int] = []
    slow = threading.Thread(target=_get_document, args=(client, results))
    slow.start()
    try:
        time.sleep(SLOW_SECONDS / 4)  # let the slow request reach the database
        started = time.perf_counter()
        probe = client.get("/probe")
        probe_seconds = time.perf_counter() - started
    finally:
        slow.join()

    assert probe.status_code == 200
    assert results == [200]
    assert probe_seconds < SLOW_SECONDS / 2, (
        f"A trivial request took {probe_seconds:.2f}s while one document "
        f"request was in flight, so the document route is holding the event "
        f"loop and every other request queues behind it."
    )


def test_pool_when_built_from_many_threads_then_only_one_pool_is_created():
    """The lazy pool is shared by every request thread, so it needs a lock."""
    import pipeline.db.postgres_client_base as base

    built = []
    barrier = threading.Barrier(8)

    class _FakePool:
        def __init__(self, **kwargs):
            built.append(kwargs)

    client = base.PostgresClientBase.__new__(base.PostgresClientBase)
    client._pool = None
    client._pool_lock = threading.Lock()

    def race(monkeypatched_pool):
        barrier.wait()
        client._get_pool()

    original = base.ThreadedConnectionPool
    base.ThreadedConnectionPool = _FakePool
    try:
        threads = [threading.Thread(target=race, args=(None,)) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        base.ThreadedConnectionPool = original

    assert len(built) == 1, (
        f"{len(built)} connection pools were created by 8 concurrent threads; "
        "each extra pool opens its own connections and is then leaked."
    )


def test_probe_check_when_a_route_does_block_the_loop_then_it_is_detected():
    """The two tests above only mean something if blocking is detectable.

    Builds a route that deliberately does its blocking work on the event loop
    — what the document routes used to do — and shows the probe slows down.
    """
    app = FastAPI()

    @app.get("/blocking")
    async def blocking():  # noqa: D401 - deliberately wrong, for the check
        time.sleep(SLOW_SECONDS)
        return {"ok": True}

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    with TestClient(app) as client:
        held: list[int] = []

        def call_blocking():
            held.append(client.get("/blocking").status_code)

        thread = threading.Thread(target=call_blocking)
        thread.start()
        try:
            time.sleep(SLOW_SECONDS / 4)
            started = time.perf_counter()
            client.get("/probe")
            probe_seconds = time.perf_counter() - started
        finally:
            thread.join()

    assert held == [200]
    assert probe_seconds >= SLOW_SECONDS / 2, (
        "A route sleeping on the event loop did not delay the probe, so the "
        "head-of-line test above cannot detect a regression."
    )
