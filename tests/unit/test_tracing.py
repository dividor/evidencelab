"""The project-owned tracing port (``utils.tracing``): backend selection,
the no-op and LangSmith recorders, the OpenTelemetry recorder with an
in-memory exporter, and the ``traceable`` decorator."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from utils import tracing
from utils.tracing import (
    LangSmithTraceRecorder,
    NoOpTraceRecorder,
    OpenTelemetryCallbackHandler,
    OpenTelemetryTraceRecorder,
    TracingConfigError,
    build_trace_recorder,
    get_trace_recorder,
    reset_trace_recorder,
    traceable,
)

pytestmark = pytest.mark.unit

_FAKE_KEY = "ls-key"


_ENV_VARS = (
    "TRACING_PROVIDER",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_PROJECT",
    "LANGCHAIN_PROJECT",
    "TRACE_URL_TEMPLATE",
)


@pytest.fixture(autouse=True)
def _fresh_recorder():
    """Start each test with no tracing environment and restore it after.

    ``LangSmithTraceRecorder.configure_environment`` writes ``LANGCHAIN_*``
    variables straight into ``os.environ``; a plain ``monkeypatch.delenv`` of
    a variable that did not exist does not undo that, so the snapshot is
    restored by hand.
    """
    import os

    saved = {var: os.environ.get(var) for var in _ENV_VARS}
    for var in _ENV_VARS:
        os.environ.pop(var, None)
    reset_trace_recorder()
    yield
    for var, value in saved.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value
    reset_trace_recorder()


def _memory_provider():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class TestSelection:
    def test_unset_without_key_is_noop(self):
        assert isinstance(build_trace_recorder({}), NoOpTraceRecorder)

    def test_unset_with_langsmith_key_keeps_langsmith(self, monkeypatch):
        """Deployments that predate TRACING_PROVIDER keep tracing to LangSmith."""
        monkeypatch.setenv("LANGSMITH_API_KEY", _FAKE_KEY)
        recorder = build_trace_recorder({"LANGSMITH_API_KEY": _FAKE_KEY})
        assert isinstance(recorder, LangSmithTraceRecorder)

    def test_explicit_none_beats_a_present_key(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_API_KEY", _FAKE_KEY)
        recorder = build_trace_recorder(
            {"LANGSMITH_API_KEY": _FAKE_KEY, "TRACING_PROVIDER": "none"}
        )
        assert isinstance(recorder, NoOpTraceRecorder)

    def test_opentelemetry_by_name(self):
        with patch.object(
            OpenTelemetryTraceRecorder,
            "_default_provider",
            return_value=TracerProvider(),
        ):
            with patch("opentelemetry.trace.set_tracer_provider") as set_provider:
                recorder = build_trace_recorder({"TRACING_PROVIDER": "otel"})
        assert isinstance(recorder, OpenTelemetryTraceRecorder)
        set_provider.assert_called_once()

    def test_unknown_name_raises(self):
        with pytest.raises(TracingConfigError, match="Unknown TRACING_PROVIDER"):
            build_trace_recorder({"TRACING_PROVIDER": "honeycomb"})

    def test_get_trace_recorder_caches_until_reset(self, monkeypatch):
        first = get_trace_recorder()
        monkeypatch.setenv("TRACING_PROVIDER", "langsmith")
        assert get_trace_recorder() is first
        reset_trace_recorder()
        assert isinstance(get_trace_recorder(), LangSmithTraceRecorder)


# ---------------------------------------------------------------------------
# No-op
# ---------------------------------------------------------------------------


class TestNoOp:
    def test_everything_is_off(self):
        recorder = NoOpTraceRecorder()
        assert recorder.enabled is False
        assert recorder.start_run() is None
        assert recorder.trace_url(uuid.uuid4()) is None
        assert recorder.callbacks() == []

    def test_wrap_returns_the_function_itself(self):
        def fn(x):
            return x + 1

        assert NoOpTraceRecorder().wrap(fn, name="n", run_type="chain") is fn

    def test_traceable_decorator_is_transparent(self):
        @traceable(name="Thing")
        def fn(x):
            return x * 2

        assert fn(21) == 42
        assert fn.__name__ == "fn"


# ---------------------------------------------------------------------------
# LangSmith
# ---------------------------------------------------------------------------


class TestLangSmith:
    def test_maps_langsmith_env_onto_langchain_names(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_API_KEY", _FAKE_KEY)
        monkeypatch.setenv("LANGSMITH_PROJECT", "proj")

        recorder = LangSmithTraceRecorder()

        import os

        assert os.environ["LANGCHAIN_API_KEY"] == _FAKE_KEY
        assert os.environ["LANGCHAIN_PROJECT"] == "proj"
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert recorder.enabled is True
        assert isinstance(recorder.start_run(), uuid.UUID)

    def test_disabled_without_key(self):
        recorder = LangSmithTraceRecorder()
        assert recorder.enabled is False
        assert recorder.start_run() is None
        assert recorder.trace_url(uuid.uuid4()) is None

    def test_trace_url_uses_public_sdk_and_caches_prefix(self, monkeypatch):
        """The link prefix comes from Client.get_run_url (public), resolved
        once, with no use of private client attributes."""
        monkeypatch.setenv("LANGSMITH_API_KEY", _FAKE_KEY)
        monkeypatch.setenv("LANGSMITH_PROJECT", "proj")
        recorder = LangSmithTraceRecorder()

        def fake_get_run_url(*, run, project_name=None, project_id=None):
            assert project_name == "proj"
            return f"https://smith.example.org/o/t1/projects/p/p1/r/{run.id}?poll=true"

        client = MagicMock()
        client.get_run_url.side_effect = fake_get_run_url
        with patch("langsmith.Client", return_value=client):
            run_a, run_b = uuid.uuid4(), uuid.uuid4()
            url_a = recorder.trace_url(run_a)
            url_b = recorder.trace_url(run_b)

        assert (
            url_a == f"https://smith.example.org/o/t1/projects/p/p1/r/{run_a}?poll=true"
        )
        assert (
            url_b == f"https://smith.example.org/o/t1/projects/p/p1/r/{run_b}?poll=true"
        )
        assert client.get_run_url.call_count == 1
        assert not client._get_tenant_id.called

    def test_trace_url_is_none_when_sdk_cannot_resolve(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_API_KEY", _FAKE_KEY)
        recorder = LangSmithTraceRecorder()
        with patch("langsmith.Client", side_effect=RuntimeError("no network")):
            assert recorder.trace_url(uuid.uuid4()) is None
            # Cached: a second call does not retry the SDK.
            assert recorder.trace_url(uuid.uuid4()) is None

    def test_wrap_delegates_to_langsmith_traceable(self):
        recorder = LangSmithTraceRecorder()
        with patch("langsmith.traceable") as ls_traceable:
            ls_traceable.return_value = lambda fn: fn

            def fn():
                return 1

            assert recorder.wrap(fn, name="Summarization", run_type="llm") is fn
        ls_traceable.assert_called_once_with(name="Summarization", run_type="llm")


# ---------------------------------------------------------------------------
# OpenTelemetry
# ---------------------------------------------------------------------------


class TestOpenTelemetry:
    def test_wrap_sync_function_records_a_span(self):
        provider, exporter = _memory_provider()
        recorder = OpenTelemetryTraceRecorder(tracer_provider=provider)

        def tag(text):
            return text.upper()

        wrapped = recorder.wrap(tag, name="TaxonomyTagger", run_type="llm")
        assert wrapped("x") == "X"
        assert wrapped.__name__ == "tag"

        (span,) = exporter.get_finished_spans()
        assert span.name == "TaxonomyTagger"
        assert span.attributes["evidencelab.run_type"] == "llm"

    def test_wrap_async_function_records_a_span(self):
        provider, exporter = _memory_provider()
        recorder = OpenTelemetryTraceRecorder(tracer_provider=provider)

        async def highlight(q):
            return f"<{q}>"

        wrapped = recorder.wrap(
            highlight, name="SemanticHighlighting", run_type="chain"
        )
        assert asyncio.run(wrapped("q")) == "<q>"
        (span,) = exporter.get_finished_spans()
        assert span.name == "SemanticHighlighting"

    def test_run_ids_and_url_template(self, monkeypatch):
        monkeypatch.setenv("TRACE_URL_TEMPLATE", "http://jaeger/search?run={run_id}")
        provider, _ = _memory_provider()
        recorder = OpenTelemetryTraceRecorder(tracer_provider=provider)

        run_id = recorder.start_run()
        assert isinstance(run_id, uuid.UUID)
        assert recorder.trace_url(run_id) == f"http://jaeger/search?run={run_id}"
        assert recorder.enabled is True

    def test_trace_url_is_none_without_template(self):
        provider, _ = _memory_provider()
        recorder = OpenTelemetryTraceRecorder(tracer_provider=provider)
        assert recorder.trace_url(uuid.uuid4()) is None

    def test_callback_handler_spans_llm_calls_with_usage(self):
        provider, exporter = _memory_provider()
        recorder = OpenTelemetryTraceRecorder(tracer_provider=provider)
        (handler,) = recorder.callbacks()
        assert isinstance(handler, OpenTelemetryCallbackHandler)

        run_id = uuid.uuid4()
        handler.on_chat_model_start(
            {"kwargs": {"model": "gpt-4.1-mini"}}, [[]], run_id=run_id
        )
        message = SimpleNamespace(
            usage_metadata={"input_tokens": 12, "output_tokens": 7}
        )
        response = SimpleNamespace(
            llm_output=None, generations=[[SimpleNamespace(message=message)]]
        )
        handler.on_llm_end(response, run_id=run_id)

        (span,) = exporter.get_finished_spans()
        assert span.name == "llm"
        assert span.attributes["evidencelab.run_id"] == str(run_id)
        assert span.attributes["gen_ai.request.model"] == "gpt-4.1-mini"
        assert span.attributes["gen_ai.usage.prompt_tokens"] == 12
        assert span.attributes["gen_ai.usage.completion_tokens"] == 7

    def test_callback_handler_prefers_llm_output_token_usage(self):
        provider, exporter = _memory_provider()
        (handler,) = OpenTelemetryTraceRecorder(tracer_provider=provider).callbacks()
        run_id = uuid.uuid4()
        handler.on_llm_start({"kwargs": {"model_name": "m"}}, ["p"], run_id=run_id)
        response = SimpleNamespace(
            llm_output={"token_usage": {"prompt_tokens": 3, "completion_tokens": 4}},
            generations=[],
        )
        handler.on_llm_end(response, run_id=run_id)
        (span,) = exporter.get_finished_spans()
        assert span.attributes["gen_ai.usage.prompt_tokens"] == 3
        assert span.attributes["gen_ai.usage.completion_tokens"] == 4

    def test_callback_handler_marks_errors(self):
        provider, exporter = _memory_provider()
        (handler,) = OpenTelemetryTraceRecorder(tracer_provider=provider).callbacks()
        run_id = uuid.uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        handler.on_llm_error(RuntimeError("rate limited"), run_id=run_id)
        (span,) = exporter.get_finished_spans()
        assert span.status.status_code.name == "ERROR"
        assert any(e.name == "exception" for e in span.events)

    def test_callback_handler_ignores_unknown_run_ids(self):
        provider, exporter = _memory_provider()
        (handler,) = OpenTelemetryTraceRecorder(tracer_provider=provider).callbacks()
        handler.on_llm_end(
            SimpleNamespace(llm_output=None, generations=[]), run_id=uuid.uuid4()
        )
        handler.on_llm_error(RuntimeError("x"), run_id=uuid.uuid4())
        assert exporter.get_finished_spans() == ()


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def test_generation_usage_handles_missing_data():
    assert (
        tracing._generation_usage(SimpleNamespace(llm_output=None, generations=[]))
        == {}
    )
    assert tracing._serialized_model(None) is None
    assert tracing._serialized_model({"kwargs": {"model": "x"}}) == "x"
