"""Project-owned LLM tracing port.

Every place that traces an LLM call goes through :class:`TraceRecorder`
rather than a vendor SDK, so the tracing backend is a deployment choice made
with ``TRACING_PROVIDER``:

- ``none``: no tracing (the default when no LangSmith key is configured).
- ``langsmith``: LangSmith, hosted or self-hosted (``LANGCHAIN_ENDPOINT``).
  Chosen automatically when ``TRACING_PROVIDER`` is unset and
  ``LANGSMITH_API_KEY`` or ``LANGCHAIN_API_KEY`` is present, which keeps
  existing deployments working unchanged.
- ``opentelemetry``: spans exported over OTLP/HTTP to any OpenTelemetry
  collector (Jaeger, Grafana Tempo, ...). The exporter reads the standard
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` and ``OTEL_SERVICE_NAME`` variables;
  ``TRACE_URL_TEMPLATE`` (with ``{run_id}``) turns a run into a link.

The port has four operations:

- ``start_run()`` returns a run id to attach to a LangChain ``config`` so the
  backend can correlate the call, or ``None`` when tracing is off.
- ``trace_url(run_id)`` returns a link to that run's trace, or ``None``.
- ``callbacks()`` returns LangChain callback handlers the backend needs in
  the call's ``config`` (LangSmith needs none; OpenTelemetry needs one).
- ``wrap(fn, name=..., run_type=...)`` instruments a function; the module
  level :func:`traceable` decorator is the convenient form.

``user_activity.trace_url`` stores the link the recorder produced; nothing
outside this module knows which backend made it.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, TypeVar

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)

PROVIDER_ENV = "TRACING_PROVIDER"

F = TypeVar("F", bound=Callable[..., Any])


class TracingConfigError(RuntimeError):
    """``TRACING_PROVIDER`` names a backend this build does not know."""


class TraceRecorder:
    """Base recorder: the no-op behaviour every backend starts from."""

    name = "none"

    @property
    def enabled(self) -> bool:
        return False

    def start_run(self) -> Optional[uuid.UUID]:
        """A run id to pass as LangChain ``config['run_id']``, or ``None``."""
        return None

    def trace_url(self, run_id: uuid.UUID) -> Optional[str]:
        """Link to the trace for ``run_id``, or ``None`` when unavailable."""
        return None

    def callbacks(self) -> List[Any]:
        """LangChain callback handlers to include in a traced call's config."""
        return []

    def wrap(self, fn: F, *, name: str, run_type: str) -> F:
        """Instrument ``fn`` as a traced unit named ``name``."""
        return fn


class NoOpTraceRecorder(TraceRecorder):
    """Tracing switched off."""


# ---------------------------------------------------------------------------
# LangSmith
# ---------------------------------------------------------------------------


class LangSmithTraceRecorder(TraceRecorder):
    """LangSmith via the MIT-licensed ``langsmith`` SDK.

    LangChain traces every LLM call on its own once the ``LANGCHAIN_*``
    variables are set, so this recorder only has to map the ``LANGSMITH_*``
    spellings onto them, mint run ids, and build trace links. Links are built
    with the SDK's public ``get_run_url`` (resolved once and cached as a
    prefix), not private client attributes.
    """

    name = "langsmith"

    def __init__(self) -> None:
        self.configure_environment()
        self._prefix: Optional[str] = None
        self._prefix_resolved = False

    @staticmethod
    def configure_environment() -> None:
        """Map ``LANGSMITH_*`` variables onto the ``LANGCHAIN_*`` names LangChain reads."""
        if os.getenv("LANGSMITH_API_KEY") and not os.getenv("LANGCHAIN_API_KEY"):
            os.environ["LANGCHAIN_API_KEY"] = os.environ["LANGSMITH_API_KEY"]
        if os.getenv("LANGSMITH_PROJECT") and not os.getenv("LANGCHAIN_PROJECT"):
            os.environ["LANGCHAIN_PROJECT"] = os.environ["LANGSMITH_PROJECT"]
        if os.getenv("LANGCHAIN_API_KEY") and not os.getenv("LANGCHAIN_TRACING_V2"):
            os.environ["LANGCHAIN_TRACING_V2"] = "true"

    @property
    def enabled(self) -> bool:
        return os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true" and bool(
            os.getenv("LANGCHAIN_API_KEY")
        )

    def start_run(self) -> Optional[uuid.UUID]:
        return uuid.uuid4() if self.enabled else None

    def trace_url(self, run_id: uuid.UUID) -> Optional[str]:
        if not self.enabled:
            return None
        prefix = self._url_prefix()
        return f"{prefix}/r/{run_id}?poll=true" if prefix else None

    def _url_prefix(self) -> Optional[str]:
        """The project's run-URL prefix, resolved once through the public SDK."""
        if self._prefix_resolved:
            return self._prefix
        self._prefix_resolved = True
        try:
            from langsmith import Client
            from langsmith.run_trees import RunTree

            probe_id = uuid.uuid4()
            project = os.getenv("LANGCHAIN_PROJECT", "default")
            probe = RunTree(
                name="evidence-lab-url-probe", id=probe_id, project_name=project
            )
            url = Client().get_run_url(run=probe, project_name=project)
            self._prefix = url.split(f"/r/{probe_id}")[0]
        except Exception as exc:
            logger.debug("Could not resolve LangSmith trace URL prefix: %s", exc)
        return self._prefix

    def wrap(self, fn: F, *, name: str, run_type: str) -> F:
        from langsmith import traceable as ls_traceable

        return ls_traceable(name=name, run_type=run_type)(fn)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# OpenTelemetry
# ---------------------------------------------------------------------------


def _generation_usage(response: Any) -> Dict[str, int]:
    """Token counts from a LangChain LLM result, whichever place carries them."""
    usage: Dict[str, int] = {}
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    for key in ("prompt_tokens", "completion_tokens"):
        if isinstance(token_usage.get(key), int):
            usage[key] = token_usage[key]
    if usage:
        return usage
    try:
        message = response.generations[0][0].message
        meta = getattr(message, "usage_metadata", None) or {}
    except (AttributeError, IndexError):
        meta = {}
    for src, dst in (
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
    ):
        if isinstance(meta.get(src), int):
            usage[dst] = meta[src]
    return usage


def _serialized_model(serialized: Optional[Dict[str, Any]]) -> Optional[str]:
    kwargs = (serialized or {}).get("kwargs") or {}
    model = kwargs.get("model") or kwargs.get("model_name")
    return str(model) if model else None


class OpenTelemetryTraceRecorder(TraceRecorder):
    """Spans over OTLP to any OpenTelemetry collector.

    Traced functions become spans named after their ``name``; each LangChain
    LLM call becomes a child ``llm`` span carrying the model, the run id and
    token counts, via the callback handler ``callbacks()`` returns.
    """

    name = "opentelemetry"

    def __init__(self, tracer_provider: Any = None) -> None:
        from opentelemetry import trace

        if tracer_provider is None:
            tracer_provider = self._default_provider()
            trace.set_tracer_provider(tracer_provider)
        self._tracer = tracer_provider.get_tracer("evidencelab")
        self._url_template = os.getenv("TRACE_URL_TEMPLATE") or None

    @staticmethod
    def _default_provider() -> Any:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "evidence-lab")}
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        return provider

    @property
    def enabled(self) -> bool:
        return True

    def start_run(self) -> Optional[uuid.UUID]:
        return uuid.uuid4()

    def trace_url(self, run_id: uuid.UUID) -> Optional[str]:
        if not self._url_template:
            return None
        return self._url_template.format(run_id=run_id)

    def callbacks(self) -> List[Any]:
        return [OpenTelemetryCallbackHandler(self._tracer)]

    def wrap(self, fn: F, *, name: str, run_type: str) -> F:
        attributes = {"evidencelab.run_type": run_type}
        tracer = self._tracer

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(name, attributes=attributes):
                    return await fn(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(name, attributes=attributes):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]


class OpenTelemetryCallbackHandler(BaseCallbackHandler):
    """One OpenTelemetry span per LangChain LLM call."""

    def __init__(self, tracer: Any) -> None:
        super().__init__()
        self._tracer = tracer
        self._spans: Dict[uuid.UUID, Any] = {}

    def _start(self, serialized: Optional[Dict[str, Any]], run_id: uuid.UUID) -> None:
        attributes: Dict[str, Any] = {"evidencelab.run_id": str(run_id)}
        model = _serialized_model(serialized)
        if model:
            attributes["gen_ai.request.model"] = model
        self._spans[run_id] = self._tracer.start_span("llm", attributes=attributes)

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        self._start(serialized, run_id)

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        self._start(serialized, run_id)

    def on_llm_end(self, response: Any, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._spans.pop(run_id, None)
        if span is None:
            return
        for key, value in _generation_usage(response).items():
            span.set_attribute(f"gen_ai.usage.{key}", value)
        span.end()

    def on_llm_error(
        self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any
    ) -> None:
        span = self._spans.pop(run_id, None)
        if span is None:
            return
        from opentelemetry.trace import Status, StatusCode

        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, str(error)))
        span.end()


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def build_trace_recorder(env: Mapping[str, str]) -> TraceRecorder:
    """Construct the recorder named by ``TRACING_PROVIDER`` in ``env``.

    An unset value means LangSmith when a LangSmith key is present and
    nothing otherwise, so a deployment that predates the setting keeps the
    behaviour it had.
    """
    name = (env.get(PROVIDER_ENV) or "").strip().lower()
    if not name:
        has_key = bool(env.get("LANGSMITH_API_KEY") or env.get("LANGCHAIN_API_KEY"))
        name = "langsmith" if has_key else "none"
    if name in ("none", "off"):
        return NoOpTraceRecorder()
    if name == "langsmith":
        return LangSmithTraceRecorder()
    if name in ("opentelemetry", "otel"):
        return OpenTelemetryTraceRecorder()
    raise TracingConfigError(
        f"Unknown {PROVIDER_ENV} '{name}'; expected none, langsmith or opentelemetry"
    )


_recorder: Optional[TraceRecorder] = None


def get_trace_recorder() -> TraceRecorder:
    """The process-wide recorder, built from the environment on first use."""
    global _recorder
    if _recorder is None:
        _recorder = build_trace_recorder(os.environ)
        logger.info("Tracing provider: %s", _recorder.name)
    return _recorder


def reset_trace_recorder() -> None:
    """Forget the cached recorder so the next call re-reads the environment."""
    global _recorder
    _recorder = None


def traceable(*, name: str, run_type: str = "chain") -> Callable[[F], F]:
    """Instrument a function with the configured recorder.

    Resolved when the decorator is applied (import time), so the environment
    must be loaded first; every module that uses it already loads ``.env``
    or runs inside a container with the variables set.
    """

    def decorate(fn: F) -> F:
        return get_trace_recorder().wrap(fn, name=name, run_type=run_type)

    return decorate
