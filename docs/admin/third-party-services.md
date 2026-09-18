# Optional Third-Party Services

Evidence Lab's core runs entirely on open-source components: FastAPI, React, PostgreSQL, Qdrant, Redis, Celery and LangChain. Three features can call an external service. Each is **optional**, **off or replaceable by configuration**, and has an open alternative. This page lists them, how to disable each one, and what to use instead.

| Feature | Default | Switch | Open alternatives |
|---------|---------|--------|-------------------|
| Translation of results and summaries | Google Translate (free endpoint, no key) | `TRANSLATION_PROVIDER` | LibreTranslate (self-hosted), the deployment's own LLM, or off |
| LLM tracing | Off | `LANGSMITH_API_KEY` (unset = off) | Self-hosted LangSmith via `LANGCHAIN_ENDPOINT`, or off |
| Web analytics | Off | `REACT_APP_GA_MEASUREMENT_ID` (unset = off) | Off, or swap the loader script for another provider |

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

Tracing records each LLM call (prompt, response, token counts) for debugging and quality work. It is a developer tool, not a product feature, and is **off unless configured**: with `LANGSMITH_API_KEY` unset, no trace is sent anywhere and no trace links appear. The client library is MIT-licensed and honours `LANGCHAIN_ENDPOINT`, so a self-hosted LangSmith instance can replace the hosted service.

## Web analytics

Google Analytics is loaded only when `REACT_APP_GA_MEASUREMENT_ID` is set at build time **and** the visitor accepts analytics cookies in the consent banner. With the variable unset, no analytics script is loaded and no third-party request is made. Visitors can withdraw consent from the Privacy page at any time. See [Privacy](../overview/privacy.md) for what is collected.
