# Evidence Lab

AI-powered document analysis and search platform. Ingests PDFs/Word docs through a processing pipeline (parse, chunk, summarize, tag, index) and exposes hybrid semantic search, a research assistant, and AI protocol integrations (MCP, A2A).

## Architecture

Monorepo with five subsystems sharing `config.json` and databases:

```
pipeline/          # Document processing (Celery workers, Docling parsing, LLM tagging)
ui/backend/        # FastAPI REST API (port 8000) — search, assistant, auth, admin
ui/frontend/       # React 18 + TypeScript SPA (port 3000)
mcp_server/        # Model Context Protocol server (port 8001) — Claude/ChatGPT integration
a2a_server/        # Agent-to-Agent protocol server (port 8001) — Google ADK, CrewAI
```

**Stack:** Python 3.11, FastAPI, Celery + Redis, SQLAlchemy 2.0, Alembic, Qdrant (vector DB), PostgreSQL 16 (pgvector), React 18, TypeScript, LangChain/LangGraph.

**Key config files:**
- `config.json` — central source of truth for datasources, models, pipeline settings, field mappings
- `.env` / `.env.example` — API keys, DB connections, feature flags, auth mode
- `docker-compose.yml` — full local dev stack (qdrant, postgres, redis, embedding-server, api, pipeline, mcp, ui)

## Commands

```bash
# Run locally (full stack)
docker compose up -d --build

# Unit tests
pytest tests/unit/ -v
docker compose exec -T pipeline pytest tests/unit/ -v

# Frontend tests
cd ui/frontend && npm test -- --watchAll=false
docker compose exec -e CI=true ui npm test -- --watchAll=false

# Integration tests (requires full Docker stack)
docker compose exec -T pipeline pytest tests/integration -v -s

# Lint / format (all hooks)
pre-commit run --all-files

# Individual linters
black .
isort --profile black .
flake8 --max-line-length=100 --extend-ignore=E203,W503 .
mypy --ignore-missing-imports --no-strict-optional .

# Code complexity check
python scripts/quality/code_metrics.py --fail-on-bad --skip-js-cognitive

# Database migrations
docker compose exec -T pipeline alembic upgrade head

# Security scans
bandit -r pipeline/ ui/backend/ -lll --exclude tests,node_modules,.venv
pip-audit -r requirements.txt --desc on
cd ui/frontend && npm audit --audit-level=high
```

## Project Rules

### Git Commits
- **NEVER use `--no-verify` when committing.** If a pre-commit hook fails, ALWAYS fix the underlying issue (lint errors, formatting, complexity, etc.) before committing again. No exceptions.
- **NEVER commit directly to `main`, `rc/v*`, or any release branch.** All changes go on a feature branch and in via PR. No exceptions.
- Use Conventional Commits format: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `perf:`, `ci:`, `build:`.

### Documentation
- **All docs MUST go in `docs/` at the repo root.** The directory `ui/frontend/public/docs/` is wiped and regenerated from `docs/` at every build by `copy-docs.js`. Anything written there will be lost on the next build.
- **`docs/docs.json` is the source of truth** for the docs sidebar. Add new pages here.

### Code Quality
- **NEVER use `noqa`, `type: ignore`, or similar suppressions to bypass pre-commit hooks or linters.** Fix the actual issue instead. Only use suppressions if explicitly requested by the user.
- **NEVER code fallbacks or graceful degradation unless explicitly requested.** If a dependency or feature is required, fail hard and loud. Silent fallbacks hide bugs.
- **NEVER install packages ad-hoc.** New dependencies MUST be added to `requirements.txt` (root) and/or `ui/backend/requirements.txt` so they are part of the build environment. Both CI and Docker must pick them up.
- **NEVER use deprecated APIs or methods.** Check library documentation for current recommended usage before implementing.

### Database
- **Use Alembic for all schema changes.** Migrations are sequentially numbered (e.g., `0019_create_api_keys_table`). Never modify the database schema directly.
- SQLAlchemy 2.0 style: use `Mapped` and `mapped_column`, not the old declarative style.
- UUID primary keys, `DateTime(timezone=True)` with UTC defaults, `JSONB` for flexible metadata.

### Verification
- **NEVER claim a task is done without actually testing it.** Run the code, check logs, verify the endpoint responds, confirm the UI renders correctly. If you can't test it, say so explicitly.

### Testing
- **All new features and functions MUST have associated unit tests.** Write tests in `tests/unit/` following existing patterns (pytest, mocking with `unittest.mock`).
- Test naming: `test_<subject>_<when>_<then>`. Class-based: `class Test*`.
- Use `@pytest.mark.unit` and `@pytest.mark.integration` markers.
- Target 90% coverage for new code.

## Code Patterns

### Backend (FastAPI)
- Router-based organization: each domain gets its own `APIRouter` in `ui/backend/routes/`.
- Auth via `verify_api_key` dependency on endpoints. Auth mode is configurable: `off`, `on_passive`, `on_active`.
- Rate limiting via `slowapi` with `@limiter.limit()` decorators per endpoint.
- Data source validation: every endpoint validates `data_source` param against `config.json`. Invalid sources error early.
- Connection pooling: `get_db_for_source()` and `get_pg_for_source()` in `ui/backend/utils/app_state.py` cache DB clients per data source.
- Pydantic models for all request/response schemas with `.model_dump()`.
- Timing instrumentation: `t0 = time.time()` ... `logger.info("[TIMING] operation: %.3fs", t1 - t0)`.

### Frontend (React/TypeScript)
- State management: React Context + custom hooks (no Redux). See `useAuth`, `useDrilldownTree`, `useActivityLogging`.
- Axios interceptors add `X-API-Key` and CSRF token headers; handle 401 retry.
- Auth cookies (`evidencelab_auth`, httpOnly) + CSRF double-submit pattern (`evidencelab_csrf`).
- Feature flags via `REACT_APP_*` env vars — **baked in at build time**, not runtime. Docker rebuild required to change.
- Config-driven: `ui/frontend/src/config.ts` reads all env vars.
- Types in `ui/frontend/src/types/` — `api.ts`, `documents.ts`, `auth.ts`.

### Pipeline
- Orchestrator pattern: `PipelineOrchestrator` runs stages sequentially (parse, chunk, summarize, tag, index).
- Stage tracking: `make_stage(success=True/False, error=None, **metadata)` for progress reporting.
- Celery tasks in `pipeline/utilities/tasks.py` for async background processing.
- Run via CLI: `python -m pipeline.orchestrator --data-source <key>`.

## Gotchas

- `ui/frontend/public/docs/` is auto-generated — never edit files there directly.
- Language filter requires a DB lookup: `_convert_language_to_doc_ids()` replaces language with doc_id filter because language isn't stored on chunks.
- API key caching: `get_active_key_hashes()` returns cached hashes — new keys won't work until cache expires.
- Search runs sync code in `run_in_threadpool()` to avoid blocking the async event loop.
- `api_key_verify.py` is extracted from `main.py` specifically to allow unit testing without loading heavy pipeline/embedding imports.
- PostgresClient uses mixins (`PostgresAdminMixin`, `PostgresDocMixin`, `PostgresChunkMixin`, `PostgresStatsMixin`) — look there for DB methods, not the base class.
- Heading normalization is lossy: `_normalize_heading_items()` flattens various formats (string/list/dict) into a list of strings.
- `code_metrics.py --fail-on-bad` runs in pre-commit — cognitive complexity > 20 will block your commit.
