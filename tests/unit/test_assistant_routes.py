"""Unit tests for research assistant API routes."""

import json
import sys
import uuid
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.requests import Request

# ---------------------------------------------------------------------------
# Mock the heavy transitive imports that assistant routes pull in.
# assistant_service -> assistant_graph -> search -> google.cloud
#
# We temporarily install lightweight mocks, import the modules we need,
# then IMMEDIATELY clean up so later test modules see the real modules.
# ---------------------------------------------------------------------------
_mock_service = ModuleType("ui.backend.services.assistant_service")


async def _noop_stream(*args, **kwargs):
    yield {"type": "done", "messageId": "msg-1"}


_mock_service.stream_research_response = _noop_stream

# Mock search module since assistant_graph imports search_chunks
_mock_search_rt = ModuleType("ui.backend.services.search")
_mock_search_rt.search_chunks = MagicMock(return_value=[])

# assistant_service mock must persist because test methods lazily import
# from ui.backend.routes.assistant which needs it.
sys.modules.setdefault("ui.backend.services.assistant_service", _mock_service)

# search mock is only needed to satisfy transitive imports; clean it up
# immediately after to avoid leaking to other test modules.
_saved_search_rt = sys.modules.get("ui.backend.services.search")
sys.modules.setdefault("ui.backend.services.search", _mock_search_rt)

from ui.backend.auth.schemas import AssistantChatRequest  # noqa: E402
from ui.backend.utils.app_limits import limiter  # noqa: E402

# Immediately restore search in sys.modules so other test files are not
# affected.
if _saved_search_rt is not None:
    sys.modules["ui.backend.services.search"] = _saved_search_rt
else:
    sys.modules.pop("ui.backend.services.search", None)

# Also clean up the package attribute set by the import machinery.
import ui.backend.services as _svc_pkg_rt  # noqa: E402

try:
    delattr(_svc_pkg_rt, "search")
except AttributeError:
    pass

# Disable rate limiting for tests
limiter.enabled = False

_test_app = FastAPI()


def _make_request(method: str = "POST", path: str = "/") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 1234),
        "app": _test_app,
    }
    return Request(scope)


class TestAssistantChatRequest:
    """Tests for the AssistantChatRequest schema used by the route."""

    def test_valid_request(self):
        req = AssistantChatRequest(query="What is food security?")
        assert req.query == "What is food security?"

    def test_request_with_all_fields(self):
        req = AssistantChatRequest(
            query="Tell me about nutrition",
            thread_id=str(uuid.uuid4()),
            data_source="test_collection",
            assistant_model_config={
                "model": "gpt-4.1-mini",
                "max_tokens": 2000,
                "temperature": 0.2,
            },
        )
        assert req.data_source == "test_collection"
        assert req.assistant_model_config.model == "gpt-4.1-mini"

    def test_query_too_long(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AssistantChatRequest(query="x" * 5001)


class TestStreamAssistantChat:
    """Tests for the /assistant/chat/stream endpoint."""

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_returns_streaming_response(self, mock_stream):
        """The endpoint should return a StreamingResponse."""

        async def mock_gen(*args, **kwargs):
            yield {"type": "phase", "phase": "planning"}
            yield {"type": "plan", "queries": ["test query"]}
            yield {"type": "phase", "phase": "synthesizing"}
            yield {"type": "token", "token": "Result text"}
            yield {"type": "done", "messageId": "msg-1"}

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(query="What is food security?")

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        assert response.media_type == "text/event-stream"
        assert response.headers.get("Cache-Control") == "no-cache"

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_sse_event_format(self, mock_stream):
        """SSE events should be formatted as 'data: {...}\\n\\n'."""
        events = [
            {"type": "phase", "phase": "planning"},
            {"type": "done", "messageId": "msg-1"},
        ]

        async def mock_gen(*args, **kwargs):
            for e in events:
                yield e

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(query="test")

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        # Collect all chunks from the streaming response
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Each chunk should be "data: {json}\n\n"
        for chunk in chunks:
            assert chunk.startswith("data: ")
            assert chunk.endswith("\n\n")
            # The JSON should parse
            data = json.loads(chunk[len("data: ") : -2])
            assert "type" in data

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_passes_model_config(self, mock_stream):
        """Model config should be extracted and passed to the service."""

        async def mock_gen(*args, **kwargs):
            yield {"type": "done", "messageId": "msg-1"}

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(
            query="test",
            assistant_model_config={
                "model": "gpt-4.1-mini",
                "max_tokens": 3000,
                "temperature": 0.5,
            },
        )

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        # Must consume the response body to trigger the event generator
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Verify stream_research_response was called with the right params
        mock_stream.assert_called_once()
        call_kwargs = mock_stream.call_args[1]
        assert call_kwargs["model_key"] == "gpt-4.1-mini"
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 3000

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_handles_stream_error(self, mock_stream):
        """Errors during streaming should yield error events."""

        async def mock_gen(*args, **kwargs):
            yield {"type": "phase", "phase": "planning"}
            raise RuntimeError("LLM failed")

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(query="test")

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Last event should be an error
        last_data = json.loads(chunks[-1][len("data: ") : -2])
        assert last_data["type"] == "error"
        assert "LLM failed" in last_data["error"]


class TestSSEEventTypes:
    """Tests for all SSE event types emitted by the stream."""

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_all_event_types(self, mock_stream):
        """Verify all event types are properly serialized."""
        events = [
            {"type": "phase", "phase": "planning"},
            {"type": "plan", "queries": ["q1", "q2"]},
            {"type": "phase", "phase": "searching"},
            {"type": "search_status", "query": "q1", "result_count": 15},
            {"type": "phase", "phase": "synthesizing"},
            {"type": "token", "token": "The answer is..."},
            {
                "type": "sources",
                "sources": [
                    {
                        "chunkId": "c1",
                        "docId": "d1",
                        "title": "Doc",
                        "text": "T",
                        "score": 0.9,
                    }
                ],
            },
            {"type": "phase", "phase": "reflecting"},
            {"type": "done", "messageId": "msg-1"},
        ]

        async def mock_gen(*args, **kwargs):
            for e in events:
                yield e

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(query="test")

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == len(events)

        # Verify each event type
        parsed_events = [json.loads(c[len("data: ") : -2]) for c in chunks]
        types = [e["type"] for e in parsed_events]

        assert "phase" in types
        assert "plan" in types
        assert "search_status" in types
        assert "token" in types
        assert "sources" in types
        assert "done" in types

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_synthesis_text_tracked_for_persistence(self, mock_stream):
        """The event_generator should track token text for persistence."""
        events = [
            {"type": "token", "token": "Research findings..."},
            {
                "type": "sources",
                "sources": [{"chunkId": "c1", "docId": "d1", "title": "D"}],
            },
            {"type": "done", "messageId": "msg-1"},
        ]

        async def mock_gen(*args, **kwargs):
            for e in events:
                yield e

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(query="test")

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # All events should be streamed without error
        parsed = [json.loads(c[len("data: ") : -2]) for c in chunks]
        types = [e["type"] for e in parsed]
        assert types == ["token", "sources", "done"]

        # The token text should appear in the streamed token event
        token_event = parsed[0]
        assert token_event["token"] == "Research findings..."


class TestSearchSettingsPassthrough:
    """Tests for search_settings being forwarded to the service layer."""

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_passes_search_settings(self, mock_stream):
        """Search settings from the request should reach the service."""

        async def mock_gen(*args, **kwargs):
            yield {"type": "done", "messageId": "msg-1"}

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(
            query="test",
            search_settings={
                "dense_weight": 0.6,
                "recency_boost": True,
                "min_chunk_size": 200,
            },
        )

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        # Consume response to trigger the event generator
        async for _ in response.body_iterator:
            pass

        mock_stream.assert_called_once()
        call_kwargs = mock_stream.call_args[1]
        settings = call_kwargs.get("search_settings")
        assert settings is not None
        assert settings["dense_weight"] == 0.6
        assert settings["recency_boost"] is True
        assert settings["min_chunk_size"] == 200

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_no_search_settings(self, mock_stream):
        """When no search_settings given, None should be passed."""

        async def mock_gen(*args, **kwargs):
            yield {"type": "done", "messageId": "msg-1"}

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(query="test")

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        async for _ in response.body_iterator:
            pass

        call_kwargs = mock_stream.call_args[1]
        assert call_kwargs.get("search_settings") is None

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_passes_reranker_model(self, mock_stream):
        """reranker_model from request should reach the service."""

        async def mock_gen(*args, **kwargs):
            yield {"type": "done", "messageId": "msg-1"}

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(
            query="test",
            reranker_model="cohere-rerank-v3",
        )

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        async for _ in response.body_iterator:
            pass

        call_kwargs = mock_stream.call_args[1]
        assert call_kwargs.get("reranker_model") == "cohere-rerank-v3"

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_passes_system_prompt_override(self, mock_stream):
        """system_prompt_override should be passed to the service (None for anon)."""

        async def mock_gen(*args, **kwargs):
            yield {"type": "done", "messageId": "msg-1"}

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(query="test")

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        async for _ in response.body_iterator:
            pass

        call_kwargs = mock_stream.call_args[1]
        # Without a user/session, group prompt resolves to None
        assert call_kwargs.get("system_prompt_override") is None

    @pytest.mark.asyncio
    @patch("ui.backend.routes.assistant.stream_research_response")
    async def test_passes_field_boost_settings(self, mock_stream):
        """field_boost settings should reach the service via search_settings."""

        async def mock_gen(*args, **kwargs):
            yield {"type": "done", "messageId": "msg-1"}

        mock_stream.return_value = mock_gen()

        from ui.backend.routes.assistant import stream_assistant_chat

        request = _make_request(path="/assistant/chat/stream")
        body = AssistantChatRequest(
            query="test",
            search_settings={
                "field_boost_enabled": True,
                "field_boost_fields": {"country": 0.5},
                "dense_weight": 0.7,
            },
        )

        response = await stream_assistant_chat(
            request=request,
            body=body,
            user=None,
            session=None,
        )

        async for _ in response.body_iterator:
            pass

        call_kwargs = mock_stream.call_args[1]
        settings = call_kwargs.get("search_settings")
        assert settings is not None
        assert settings["field_boost_enabled"] is True
        assert settings["field_boost_fields"] == {"country": 0.5}
        assert settings["dense_weight"] == 0.7
