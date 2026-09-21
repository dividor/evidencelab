# Optional Third-Party Services

Evidence Lab's core runs entirely on open-source components: FastAPI, React, PostgreSQL, Qdrant, Redis, Celery and LangChain. Three features can call an external service. Each is **optional**, **off or replaceable by configuration**, and has an open alternative. This page lists them, how to disable each one, and what to use instead.

| Feature | Default | Switch | Open alternatives |
|---------|---------|--------|-------------------|
| Translation of results and summaries | Google Translate (free endpoint, no key) | `TRANSLATION_PROVIDER` | LibreTranslate (self-hosted), the deployment's own LLM, or off |
| LLM tracing | Off | `TRACING_PROVIDER` | OpenTelemetry (any collector), self-hosted LangSmith, or off |
| Web analytics | Off | `REACT_APP_GA_MEASUREMENT_ID` (unset = off) | Off, or another provider via the analytics module |

The LLM and embedding models themselves are chosen in `config.json` and can be commercial APIs (OpenAI, Anthropic, Azure, Vertex) or self-hosted open models (Hugging Face, any OpenAI-compatible server). See [Pipeline Configuration](pipeline-configuration.md).

## Translation

Search results, AI summaries and document text can be translated into the reader's language on request. The provider that performs the translation is selected with `TRANSLATION_PROVIDER` in `.env`:

| Value | What it does | Extra settings |
|-------|--------------|----------------|
| `google` (default) | Google Translate via the MIT-licensed [deep-translator](https://github.com/nidhaloff/deep-translator) library. Uses Google's free web endpoint, so no key is needed, but every request leaves your infrastructure. | none |
| `libretranslate` | A [LibreTranslate](https://libretranslate.com/) server (AGPL, self-hostable, runs offline). | `LIBRETRANSLATE_URL` (required), `LIBRETRANSLATE_API_KEY` (if your server requires one) |
| `llm` | The deployment's own configured LLM, through the same model factory as every other AI feature. | `TRANSLATION_LLM_MODEL` (optional model key from `config.json`; unset uses the default model) |
| `off` | Translation is disabled. The `/translate` endpoint and the `target_language` parameter on document endpoints answer `501 Not Implemented`; the UI shows the original text. | none |

All providers share the same wrapper, which protects citation references such as `[12]` and paragraph breaks from being mangled and splits long texts into pieces under the provider's request limit. Adding another provider means implementing one method on `TranslationProvider` in `ui/backend/services/translation_providers.py`.

### Running LibreTranslate alongside Evidence Lab

Add a service to your compose file and point the API at it:

```yaml
libretranslate:
  image: libretranslate/libretranslate
  environment:
    - LT_LOAD_ONLY=en,fr,es,ar,zh,pt,ru
  ports:
    - "5000:5000"
```

```bash
TRANSLATION_PROVIDER=libretranslate
LIBRETRANSLATE_URL=http://libretranslate:5000
```

The language codes Evidence Lab sends are ISO 639-1 (`fr`, `zh`, ...), which LibreTranslate accepts directly.

## LLM tracing

Tracing records each LLM call (prompt, response, token counts) for debugging and quality work. It is a developer tool, not a product feature, and is **off unless configured**. All tracing goes through one project-owned port, `utils/tracing.py`, so the backend is a deployment choice made with `TRACING_PROVIDER` in `.env`:

| Value | What it does | Extra settings |
|-------|--------------|----------------|
| `none` (default) | No tracing. Nothing is sent anywhere and no trace links appear. | none |
| `opentelemetry` | Spans are exported over OTLP/HTTP to any [OpenTelemetry](https://opentelemetry.io/) collector (Jaeger, Grafana Tempo, SigNoz, ...), all open source and self-hostable. Each traced step is a span; each LLM call is a child span carrying the model, run id and token counts. | `OTEL_EXPORTER_OTLP_ENDPOINT` (collector URL), `OTEL_SERVICE_NAME` (default `evidence-lab`), `TRACE_URL_TEMPLATE` (optional; `{run_id}` is substituted to build a link to the trace) |
| `langsmith` | LangSmith, hosted or self-hosted. The client library is MIT-licensed and honours `LANGCHAIN_ENDPOINT`, so a self-hosted instance can replace the hosted service. | `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGCHAIN_ENDPOINT` (self-hosted) |

When `TRACING_PROVIDER` is unset, LangSmith is used if `LANGSMITH_API_KEY` is set and nothing otherwise, so deployments that predate the setting keep the behaviour they had.

Trace links are stored in the vendor-neutral `user_activity.trace_url` column and returned on the AI summary and assistant completion events as `trace_url`. Adding another backend means implementing the four-method `TraceRecorder` class in `utils/tracing.py`.

### Running an OpenTelemetry collector alongside Evidence Lab

Jaeger's all-in-one image accepts OTLP directly:

```yaml
jaeger:
  image: jaegertracing/all-in-one:1.60
  ports:
    - "16686:16686"   # UI
    - "4318:4318"     # OTLP/HTTP
```

```bash
TRACING_PROVIDER=opentelemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
OTEL_SERVICE_NAME=evidence-lab
```

## Web analytics

Google Analytics is loaded only when `REACT_APP_GA_MEASUREMENT_ID` is set at build time **and** the visitor accepts analytics cookies in the consent banner. With the variable unset, no analytics script is loaded and no third-party request is made. Visitors can withdraw consent from the Privacy page at any time. See [Privacy](../overview/privacy.md) for what is collected.

The vendor script is injected by `ui/frontend/src/utils/analytics.ts`, not by the HTML page, and the Content-Security-Policy carries no inline-script hash. To use another provider (for example self-hosted [Plausible](https://plausible.io/) or [Matomo](https://matomo.org/)), implement the two-method `AnalyticsProvider` interface in that file and return it from `createAnalyticsProvider()`; the consent banner and the Privacy-page toggle work unchanged.
