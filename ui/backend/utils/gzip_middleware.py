"""Gzip response compression that leaves event streams alone.

Why this exists instead of Starlette's ``GZipMiddleware``: the Starlette
version pinned by ``ui/backend/requirements.txt`` (0.41) compresses every
response, including ``text/event-stream``. Gzip holds streamed bytes in its
internal buffer until the stream closes, so the assistant and AI summary
streams would reach the browser all at once at the very end instead of
token by token. Starlette 0.52 skips event streams itself, but the API
image does not run that version.

Behaviour:

- Responses are compressed only when the client sends ``Accept-Encoding``
  containing ``gzip``.
- Bodies smaller than ``minimum_size`` are sent as-is.
- Responses whose ``Content-Type`` starts with one of
  ``EXCLUDED_CONTENT_TYPES``, or that already carry ``Content-Encoding``,
  are passed through untouched.
- Streamed responses (more than one body message) are compressed chunk by
  chunk with a sync flush after each chunk, so downloads still progress as
  the server produces them.
"""

import zlib
from typing import Optional

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

EXCLUDED_CONTENT_TYPES = ("text/event-stream",)

# 16 + MAX_WBITS asks zlib for a gzip container rather than a raw deflate
# stream, which is what browsers expect for ``Content-Encoding: gzip``.
_GZIP_WBITS = 16 + zlib.MAX_WBITS


class SelectiveGZipMiddleware:
    """Pure-ASGI middleware: gzip responses except event streams."""

    def __init__(self, app: ASGIApp, minimum_size: int = 1024, compresslevel: int = 6):
        if not 0 <= compresslevel <= 9:
            raise ValueError(f"compresslevel must be 0..9, got {compresslevel}")
        if minimum_size < 0:
            raise ValueError(f"minimum_size must be >= 0, got {minimum_size}")
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        accept_encoding = Headers(scope=scope).get("accept-encoding", "")
        if "gzip" not in accept_encoding:
            await self.app(scope, receive, send)
            return
        responder = _GZipResponder(send, self.minimum_size, self.compresslevel)
        await self.app(scope, receive, responder.send)


class _GZipResponder:
    """Wraps one response's ``send`` and decides per response what to do."""

    def __init__(self, send: Send, minimum_size: int, compresslevel: int):
        self._send = send
        self._minimum_size = minimum_size
        self._compresslevel = compresslevel
        self._start_message: Optional[Message] = None
        self._passthrough = False
        self._body_started = False
        self._compressor: Optional["zlib._Compress"] = None

    async def send(self, message: Message) -> None:
        kind = message["type"]
        if kind == "http.response.start":
            self._remember_start(message)
        elif kind == "http.response.body" and not self._passthrough:
            await self._send_body(message)
        else:
            # Excluded content, already-encoded responses and non-body
            # messages such as ``http.response.pathsend`` go through as-is.
            await self._send_start_once()
            await self._send(message)

    def _remember_start(self, message: Message) -> None:
        # Headers cannot be finalised until the first body message shows
        # whether the response is small, single-shot, or streamed.
        self._start_message = message
        headers = Headers(raw=message["headers"])
        content_type = headers.get("content-type", "")
        self._passthrough = "content-encoding" in headers or content_type.startswith(
            EXCLUDED_CONTENT_TYPES
        )

    async def _send_start_once(self) -> None:
        if self._start_message is not None:
            start, self._start_message = self._start_message, None
            await self._send(start)

    async def _send_body(self, message: Message) -> None:
        body = message.get("body", b"")
        more_body = message.get("more_body", False)
        if self._body_started:
            message["body"] = self._compress(body, more_body)
            await self._send(message)
            return

        self._body_started = True
        if not more_body and len(body) < self._minimum_size:
            await self._send_start_once()
            await self._send(message)
            return

        if self._start_message is None:
            raise RuntimeError("http.response.body received before http.response.start")
        headers = MutableHeaders(raw=self._start_message["headers"])
        headers["Content-Encoding"] = "gzip"
        headers.add_vary_header("Accept-Encoding")
        self._compressor = zlib.compressobj(
            self._compresslevel, zlib.DEFLATED, _GZIP_WBITS
        )
        message["body"] = self._compress(body, more_body)
        if more_body:
            del headers["Content-Length"]
        else:
            headers["Content-Length"] = str(len(message["body"]))
        await self._send_start_once()
        await self._send(message)

    def _compress(self, body: bytes, more_body: bool) -> bytes:
        if self._compressor is None:
            raise RuntimeError("compressor used before the response started")
        out = self._compressor.compress(body)
        flush_mode = zlib.Z_SYNC_FLUSH if more_body else zlib.Z_FINISH
        return out + self._compressor.flush(flush_mode)
