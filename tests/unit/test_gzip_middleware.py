"""Unit tests for SelectiveGZipMiddleware (API response compression)."""

import asyncio
import gzip
import json
import zlib

import httpx
import pytest
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse

from ui.backend.utils.gzip_middleware import SelectiveGZipMiddleware

LARGE_PAYLOAD = {"results": [{"text": "chunk " * 50, "id": i} for i in range(200)]}
SMALL_PAYLOAD = {"status": "ok"}
STREAM_CHUNKS = [f"data: event {i} {'x' * 300}\n\n" for i in range(5)]
CSV_ROWS = [f"row{i}," + "value" * 100 + "\n" for i in range(5)]


def _make_app(minimum_size: int = 1024, compresslevel: int = 6) -> FastAPI:
    app = FastAPI()

    @app.get("/large")
    async def large():
        return LARGE_PAYLOAD

    @app.get("/small")
    async def small():
        return SMALL_PAYLOAD

    @app.get("/sse")
    async def sse():
        async def gen():
            for chunk in STREAM_CHUNKS:
                yield chunk
                await asyncio.sleep(0)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/csv")
    async def csv():
        async def gen():
            for row in CSV_ROWS:
                yield row

        return StreamingResponse(gen(), media_type="text/csv")

    @app.get("/pre-encoded")
    async def pre_encoded():
        body = gzip.compress(b"already compressed " * 200)
        return Response(
            content=body,
            media_type="application/octet-stream",
            headers={"Content-Encoding": "gzip"},
        )

    app.add_middleware(
        SelectiveGZipMiddleware, minimum_size=minimum_size, compresslevel=compresslevel
    )
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def _call_asgi(app: FastAPI, path: str, request_headers: list) -> tuple:
    """Drive the app at the ASGI level and capture the exact messages sent.

    Returns ``(response_headers, body_messages)`` where ``body_messages`` is
    the list of raw ``body`` bytes for every ``http.response.body`` message,
    in the order the middleware emitted them.
    """
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": request_headers,
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("client", 1),
    }
    request_delivered = False

    async def receive():
        nonlocal request_delivered
        if not request_delivered:
            request_delivered = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()

    headers: dict = {}
    bodies: list = []

    async def send(message):
        if message["type"] == "http.response.start":
            headers.update({k.decode(): v.decode() for k, v in message["headers"]})
        elif message["type"] == "http.response.body":
            bodies.append(message.get("body", b""))

    await app(scope, receive, send)
    return headers, bodies


GZIP_REQUEST = [(b"accept-encoding", b"gzip, deflate, br"), (b"host", b"testserver")]
PLAIN_REQUEST = [(b"host", b"testserver")]


@pytest.mark.unit
class TestSelectiveGZipMiddleware:
    @pytest.mark.asyncio
    async def test_large_json_when_gzip_accepted_then_compressed_and_decodable(self):
        headers, bodies = await _call_asgi(_make_app(), "/large", GZIP_REQUEST)
        assert headers["content-encoding"] == "gzip"
        assert "Accept-Encoding" in headers["vary"]
        wire = b"".join(bodies)
        assert int(headers["content-length"]) == len(wire)
        assert json.loads(gzip.decompress(wire)) == LARGE_PAYLOAD
        assert len(wire) < len(json.dumps(LARGE_PAYLOAD))

    @pytest.mark.asyncio
    async def test_large_json_when_fetched_via_client_then_transparently_decoded(self):
        async with _client(_make_app()) as client:
            response = await client.get("/large", headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"
        assert response.json() == LARGE_PAYLOAD

    @pytest.mark.asyncio
    async def test_small_json_when_under_minimum_size_then_untouched(self):
        headers, bodies = await _call_asgi(_make_app(), "/small", GZIP_REQUEST)
        assert "content-encoding" not in headers
        assert json.loads(b"".join(bodies)) == SMALL_PAYLOAD

    @pytest.mark.asyncio
    async def test_large_json_when_client_does_not_accept_gzip_then_untouched(self):
        headers, bodies = await _call_asgi(_make_app(), "/large", PLAIN_REQUEST)
        assert "content-encoding" not in headers
        assert json.loads(b"".join(bodies)) == LARGE_PAYLOAD

    @pytest.mark.asyncio
    async def test_event_stream_when_gzip_accepted_then_each_event_passes_through_intact(
        self,
    ):
        headers, bodies = await _call_asgi(_make_app(), "/sse", GZIP_REQUEST)
        assert "content-encoding" not in headers
        assert headers["content-type"].startswith("text/event-stream")
        # Every event must leave the middleware as its own, unmodified message;
        # buffering them until the stream closes is exactly the bug this guards.
        emitted = [b.decode() for b in bodies if b]
        assert emitted == STREAM_CHUNKS

    @pytest.mark.asyncio
    async def test_streamed_csv_when_gzip_accepted_then_each_chunk_flushed_promptly(
        self,
    ):
        headers, bodies = await _call_asgi(_make_app(), "/csv", GZIP_REQUEST)
        assert headers["content-encoding"] == "gzip"
        assert "content-length" not in headers
        # Each row is one body message with more_body=True; a sync flush per
        # chunk means none of them arrives empty (which would signal buffering).
        row_messages = bodies[: len(CSV_ROWS)]
        assert all(len(b) > 0 for b in row_messages)
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        assert decoder.decompress(b"".join(bodies)).decode() == "".join(CSV_ROWS)

    @pytest.mark.asyncio
    async def test_already_encoded_response_when_gzip_accepted_then_not_double_compressed(
        self,
    ):
        headers, bodies = await _call_asgi(_make_app(), "/pre-encoded", GZIP_REQUEST)
        assert headers["content-encoding"] == "gzip"
        assert gzip.decompress(b"".join(bodies)) == b"already compressed " * 200

    @pytest.mark.asyncio
    async def test_non_http_scope_when_called_then_passed_straight_to_app(self):
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        middleware = SelectiveGZipMiddleware(inner)
        await middleware({"type": "lifespan"}, None, None)
        assert seen == ["lifespan"]

    def test_init_when_compresslevel_out_of_range_then_raises(self):
        with pytest.raises(ValueError):
            SelectiveGZipMiddleware(lambda *a: None, compresslevel=10)

    def test_init_when_minimum_size_negative_then_raises(self):
        with pytest.raises(ValueError):
            SelectiveGZipMiddleware(lambda *a: None, minimum_size=-1)


@pytest.mark.unit
class TestAppRegistration:
    """The real API app registers the middleware from environment settings."""

    @staticmethod
    def _reload_main(extra_env: dict):
        import importlib
        import os
        from unittest.mock import patch

        env = {k: v for k, v in os.environ.items() if not k.startswith("API_GZIP_")}
        env["API_SECRET_KEY"] = ""
        env.update(extra_env)
        with patch.dict(os.environ, env, clear=True):
            import ui.backend.main as main_module

            return importlib.reload(main_module)

    @staticmethod
    def _gzip_entries(main_module):
        return [
            m
            for m in main_module.app.user_middleware
            if m.cls is SelectiveGZipMiddleware
        ]

    def test_app_when_env_unset_then_gzip_registered_with_defaults(self):
        main_module = self._reload_main({})
        entries = self._gzip_entries(main_module)
        assert len(entries) == 1
        assert entries[0].kwargs == {"minimum_size": 1024, "compresslevel": 6}

    def test_app_when_env_overrides_then_gzip_uses_them(self):
        main_module = self._reload_main(
            {"API_GZIP_MIN_BYTES": "4096", "API_GZIP_LEVEL": "3"}
        )
        entries = self._gzip_entries(main_module)
        assert entries[0].kwargs == {"minimum_size": 4096, "compresslevel": 3}

    def test_app_when_disabled_then_gzip_not_registered(self):
        main_module = self._reload_main({"API_GZIP_ENABLED": "false"})
        assert self._gzip_entries(main_module) == []
