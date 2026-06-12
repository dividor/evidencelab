# Changelog

All notable changes to Evidence Lab will be documented in this file.

## [1.5.1] - 2026-06-11

Evidence Lab v1.5.1 is a hotfix release that repairs the host-mode demo (`scripts/demo/run_demo.py --mode host`) following the README quickstart. Two bugs made a vanilla host run fail before any documents were indexed; both are now fixed and covered by regression tests.

### Fixed
- **Summarizer no longer requires a HuggingFace token for non-HuggingFace providers.** `SummarizeProcessor.setup()` demanded `HUGGINGFACE_API_KEY` unconditionally, even though the token is unused unless the LLM provider is HuggingFace. This blocked the demo's default **Azure Foundry** provider (and Google Vertex) for users supplying only their provider's own credentials. The requirement is now scoped to `provider == "huggingface"`.
- **Empty `DATA_MOUNT_PATH` no longer breaks host-mode document scanning.** `.env.example` ships `DATA_MOUNT_PATH=` (empty); in host mode `os.getenv("DATA_MOUNT_PATH", "./data")` returned `""` (a present-but-empty var defeats the default), collapsing the scan path to an absolute `/<source>/pdfs` so no documents were found. Added `resolve_data_mount_path()` (treats empty as the `./data` default) and routed all host path-resolution sites through it. Docker mode was unaffected (it sets `DATA_MOUNT_PATH=/app/data` explicitly).

### Tests
- Added regression tests for `resolve_data_mount_path()` (empty/unset/set) and for the summarizer's provider-scoped HuggingFace requirement.

**Full diff:** https://github.com/dividor/evidencelab/compare/v1.5.0...v1.5.1

---

## [1.5.0] - 2026-06-11

Evidence Lab v1.5.0 is a feature release focused on admin observability, research and assistant quality, and operational tooling. It adds LLM token/cost tracking and an admin usage dashboard, a page feedback button with screenshot capture, a polished Word export, sliding auth sessions, and a number of search/facet/research fixes.

### Admin & Observability
- Added an **LLM Usage** admin tab with per-user and per-group token and cost rollups (#310)
- Tracked LLM model, token usage, and cost in the admin Activity tab (#310)
- Added an admin response field to ratings for triage tracking (#308)
- Added a **See more / Show less** toggle to the ratings comment column (#300)
- Rendered screenshot data URLs as images in the activity table, robust to inline span layout (#292)

### Feedback & Export
- Added a page feedback button with screenshot capture — captures viewport only and freezes animations during capture, excludes modal/loading overlays (#284, #292)
- Polished the Word export: bigger blue H1, numbered references, clickable citations, and a gated export button (#293, #295)

### Research & Assistant
- Split drilldown into **sub-topic** vs **new-topic** modes — new-topic resets the drilldown chain instead of nesting, and the breadcrumb now shows the full ancestor path (#299)
- Inherited parent context into the search query (not just the summary) for "find out more" drilldowns (#299)
- Preserved assistant citations across follow-up turns (#303)
- Picked up Gemini synthesis when emitted alongside `write_todos` in the deep-research path (#294)

### Search & Facets
- Resolved `src_*` filter values and counts via Postgres JSONB on query-narrowed search (#298)
- Used backend query-narrowed counts for the sidebar facets instead of re-counting visible results (#296)
- Collapsed `en` and `English` into a single Language facet entry (#296)
- Fell back to no-rerank when the Vertex Discovery Engine returns 503 (#301)

### Authentication
- Added sliding session refresh — active users are re-issued their auth cookie every half-lifetime (`POST /auth/refresh`) so they are never logged out mid-session; idle sessions still lapse at `AUTH_TOKEN_LIFETIME` (#328)
- Preserved search URL params across the OAuth login round-trip (#303)

### Operational Tooling & Data
- Added a global backup orchestration script (#283)
- Validated the Postgres dump archive with `pg_restore` before declaring a backup successful (#307)
- Added a `fix_duplicate_countries` cleanup script (#327)
- Scripted rename of country `Syria` to `Syrian Arab Republic` (#297)

### CI & Dependencies
- Auto-merge Dependabot patch and minor bumps (#326)
- Updated dependabot target-branch to `rc/v1.5.0`
- Dependency bumps: sqlalchemy 2.0.49 (#277), uvicorn 0.44.0 (#282), ajv 8.20.0 (#289, #320), @playwright/test 1.60.0 (#279, #314), @typescript-eslint/parser (#287, #321), pytest-playwright 0.8.0 (#316), google-cloud-aiplatform (#313), langgraph-checkpoint-postgres (#312), gitleaks-action v3 (#311)

### Upgrade Notes
- **Database migrations apply automatically on deploy.** The API container runs `alembic upgrade head` on startup (before uvicorn), so redeploying picks up this release's new migrations (`0026_add_activity_token_usage`, `0026_add_rating_response`, merged by `0027_merge_0026_heads`) — no manual step required.
- **New optional env vars** (defaults preserve current behaviour): `AUTH_TOKEN_LIFETIME` (default 3600s) and `AUTH_IDLE_TIMEOUT` (default 3600s) — see `.env.example`.

**Full diff:** https://github.com/dividor/evidencelab/compare/v1.4.0...v1.5.0

---

## [1.4.0] - 2026-04-12

Evidence Lab v1.4.0 is a security and authentication release. It fixes a SQL injection vulnerability in the documents API, adds conditional OAuth login buttons, and improves deployment configuration for OAuth callbacks.

### Security
- Fixed SQL injection via `sort_by` parameter interpolated into raw SQL — replaced f-string interpolation with whitelist dictionary lookup (#264, #266)
- Fixed SQL injection via taxonomy filter codes interpolated into `jsonb_path_exists` — replaced with parameterized `vars` argument (#264, #266)
- Added `_ALLOWED_TAXONOMY_KEYS` frozenset to validate taxonomy keys before use in JSONB path expressions (#266)
- Added "SQL Injection Prevention" section to SECURITY.md documenting all dynamic SQL controls (#266)
- Updated CLAUDE.md SQL guidance to cover dynamic SQL fragments (ORDER BY, JSONB paths) (#266)
- Added 15 regression tests for SQL injection prevention (#266)

### Authentication
- Added conditional OAuth buttons — Google and Microsoft SSO buttons only appear when the corresponding secrets are configured (#265)
- Added `DISABLE_EMAIL_LOGIN` environment variable to hide email/password login when only OAuth is desired (#265)
- Fixed OAuth secrets to be read solely from `.env` file in the API service (#265)
- Pinned langgraph and langgraph-prebuilt to working versions (#265)

### Documentation & CI
- Added `OAUTH_CALLBACK_BASE_URL` to `.env.example` and auth documentation (#261)
- Updated dependabot target-branch to `rc/v1.4.0` (#263)
- Skipped container-scan for dependabot PRs to reduce CI costs

### What's Changed
- fix: prevent SQL injection via sort_by and taxonomy filter parameters (#266)
- feat: conditional OAuth buttons and DISABLE_EMAIL_LOGIN (#265)
- ci: update dependabot target-branch to rc/v1.4.0 (#263)
- docs: add OAUTH_CALLBACK_BASE_URL to .env.example and auth docs (#261)
- ci: skip container-scan for dependabot PRs

**Full diff:** https://github.com/dividor/evidencelab/compare/v1.3.0...v1.4.0

---

## [1.3.0] - 2026-03-30

Evidence Lab v1.3.0 is a security and code quality release focused on achieving the [OpenSSF Best Practices](https://www.bestpractices.dev/projects/12335) baseline badge. It hardens the CI pipeline, enforces stricter static analysis, documents cryptographic practices, and raises the bar on code quality tooling throughout the project.

### OpenSSF Best Practices
- Achieved OpenSSF Best Practices baseline badge (#246)
- Added OpenSSF Best Practices badge to README
- Added coverage reporting to CI unit test runs (#246)
- Upgraded Bandit to 1.9.4 and raised severity threshold to MEDIUM+HIGH (#247)
- Added explicit contribution standards section to CONTRIBUTING.md (#247)
- Documented cryptographic algorithms in SECURITY.md — TLS, Argon2id, bcrypt, Fernet, SHA-256, HS256 (#247)
- Updated SECURITY.md to reflect Bandit 1.9.4 and medium severity enforcement (#247)
- Corrected mypy documentation across CLAUDE.md and CONTRIBUTING.md (#247)

### Security & CI Hardening
- Explicitly enforce TLS 1.2+ minimum in Caddyfile — rejects TLS 1.1 and below (#249)
- Set `permissions: {}` default at workflow level in CI — all jobs now default to no GitHub token permissions; jobs requiring access declare them explicitly
- Added request timeouts to all `requests` calls in scripts — fixes Bandit B113 (#247)

### Type Safety
- Removed `--no-strict-optional` from mypy configuration — full `Optional`/`None` checking now enforced across the entire codebase (#248)
- Fixed all resulting mypy errors across 44 files: `ws.active` None guards, `Sequence` vs `list` annotations, implicit Optional parameters, return type mismatches (#248)
- Extended mypy exclude to `scripts/` and `alembic/` in pre-commit config — fixes CI `--all-files` failures (#248)

### What's Changed
- feat: add coverage reporting to CI for OpenSSF badge (#246)
- docs: add explicit contribution requirements to CONTRIBUTING.md (#247)
- docs(security): update SECURITY.md for Bandit 1.9.4 and medium severity (#247)
- docs(security): document cryptographic algorithms for OpenSSF compliance (#247)
- ci: upgrade Bandit to 1.9.4, raise severity to medium+high (#247)
- fix(ci): add request timeouts to fix Bandit B113 (#247)
- fix(types): remove --no-strict-optional, fix all mypy strict-optional errors (#248)
- fix(ci): exclude scripts/ and alembic/ from mypy (#248)
- fix(tls): explicitly enforce TLS 1.2+ minimum in Caddyfile (#249)
- ci: set default workflow permissions to none for least-privilege
- docs: add OpenSSF Best Practices badge to README

**Full diff:** https://github.com/dividor/evidencelab/compare/v1.2.0...v1.3.0

---

## [1.2.0] - 2026-03-30

Evidence Lab v1.2.0 introduces native integration with external AI systems via the Model Context Protocol (MCP) and the Google Agent-to-Agent (A2A) protocol, enabling AI assistants and autonomous agents to search, retrieve, and reason over document collections directly. This release also adds a UN Mandates Registry data source, OCR support for scanned PDFs, and a range of fixes and performance improvements.

### MCP Server
- Integrated MCP server exposing document collections as tools callable by any MCP-compatible AI assistant (Claude, Cursor, etc.) (#236)
- Tools: `search`, `get_document`, `list_documents`, `get_chunk`, `search_chunks`
- API key authentication with full audit logging of every tool call
- Admin UI for browsing the MCP audit log with filtering and pagination
- OAuth 2.0 support for MCP client authentication

### A2A Server
- Google Agent-to-Agent (A2A) protocol endpoint on the same port as MCP (#240)
- Full protocol support: `tasks/send`, `tasks/sendSubscribe` (SSE streaming), `tasks/get`, `tasks/cancel`
- Research skill (full AI-assisted synthesis) and search skill (direct retrieval)
- Agent Card at `/.well-known/agent.json`
- Ownership enforcement: only the originating principal can cancel their own tasks

### New Data Source
- UN Mandates Registry data source with field mappings, filters, metadata panel, and SDG taxonomy (#226)

### OCR Fallback
- `--ocr-fallback` CLI flag and `parse.ocr_fallback` config option for scanned PDF support (#227)
- Documents parsing to fewer than 10 words are automatically retried with OCR
- Tracks `sys_ocr_applied` per document; re-processes previously failed documents

### Admin & API Keys
- API key values now stored encrypted with Fernet (AES-128-CBC) (#243)
- Copy-to-clipboard for newly generated keys in the admin panel
- `protocol` column on MCP audit log to distinguish MCP vs A2A calls

### Fixes & Improvements
- **Auth**: Added `credentials` and `X-API-Key` to all frontend fetch calls, fixing 401 errors on translate/highlight (#234, #235)
- **UI**: Fixed mobile search filter overlap (#233); removed duplicate scrollbar on document column filters (#224)
- **Stats**: Fixed bar chart showing only the first organisation (#225)
- **Vertex AI**: Added rate limiter to prevent 429 errors under load (#229)
- **Performance**: Tuned Postgres autovacuum and Qdrant write performance for large collections (#223)
- **Backups**: Fixed brotli-compressed Qdrant snapshot handling in dump/restore (#228)
- **CI**: Added Docker Hub authentication to prevent pull rate limiting (#230)
- **Docs**: Architecture diagrams, MCP and A2A connection guides (#221, #239)
- **Demo**: CI mode for automated end-to-end demo smoke tests (#242)

### Database Migrations
- `0020_add_ocr_columns` — `sys_parsed_folder` and `sys_ocr_applied` on all `docs_*` tables
- `0021_tune_autovacuum_tables` — autovacuum tuning for large document and chunk tables
- `0022_create_mcp_audit_log` — MCP/A2A tool call audit log table
- `0023_add_key_value_to_api_keys` — key value column for admin copy support
- `0024_encrypt_api_key_values` — widens key_value to 512 chars for encrypted tokens
- `0024_mcp_audit_protocol` / `0025_merge_0024_heads` — protocol column and branch merge migration

### Dependency Updates
FastAPI, Docling, PyMuPDF, RapidOCR, LangChain Core, Uvicorn, Selenium, and frontend TypeScript tooling (#206–#219).

### What's Changed
- feat: A2A agent server with research and search skills (#240)
- feat(admin): MCP/A2A audit log tab with protocol distinction (#243)
- feat: Add MCP server with search, document, and assistant tools (#236)
- feat: add UN Mandates Registry data source configuration (#226)
- feat: Add --ocr-fallback for scanned PDF support (#227)
- feat(demo): CI mode, e2e smoke tests, and demo-e2e workflow (#242)
- fix(security): harden auth, API keys, MCP/A2A, nginx — full audit remediation (#241)
- fix(auth): add credentials and API key to all frontend fetch calls (#235)
- fix: translate and highlight 401 errors with auth credentials (#234)
- fix: mobile search filter overlap (#233)
- fix(ui): remove duplicate scrollbar on document column filters (#224)
- fix(stats): show all organizations in stats bar chart (#225)
- fix: add Vertex AI rate limiter to prevent 429 errors (#229)
- fix: handle brotli-compressed Qdrant snapshots in dump/restore (#228)
- fix(ci): add Docker Hub authentication to avoid rate limiting (#230)
- fix(db): add Alembic migration for OCR fallback columns (#231)
- fix(docs): add MCP docs to root docs/ so they survive the build (#239)
- fix: miscellaneous fixes and project rename (#237)
- docs: add application architecture diagram (#221)
- docs: add UN Mandates Registry to data source pages (#232)
- docs: update SECURITY.md with missing CI security practices (#222)
- docs: comprehensive CLAUDE.md with architecture, commands, and patterns (#244)
- perf: tune Postgres autovacuum and Qdrant write performance (#223)

**Full diff:** https://github.com/dividor/evidencelab/compare/v1.1.0...v1.2.0

---

## [1.1.0] - 2026-03-18

Evidence Lab v1.1.0 brings a full user authentication and permissions system, an experimental research assistant with deep research mode, a guided interactive demo, in-system documentation, and some security hardening.

### Highlights

- **User authentication and permissions module** with groups, settings, and activity monitoring. Includes registration and sign-in via email/password, Microsoft OAuth, and Google OAuth.
- **Granular user ratings and feedback** on any AI output (search results, summaries, taxonomy tags, assistant responses) to generate evaluation and training data.
- **Experimental research tree feature** allowing users to drill down into sub-topics and build a saved research tree linked to their profile.
- **Conversational research assistant** with a deep research mode using LangGraph-based coordinator/researcher sub-agents.
- **Guided interactive demo setup** to help new users get started quickly with provider selection and API key configuration.
- **In-system help documentation library** with searchable sidebar navigation and markdown rendering.
- **Security hardening** focused on self-assessed OWASP ASVS L2 compliance, including CSRF protection, cookie-based sessions, API key enforcement, rate limiting, and audit logging.

### Research Assistant
- New Research Assistant tab with chat-based AI agent, inline citations, and expandable references (#165, #167–#173)
- Deep Research mode using LangGraph coordinator/researcher sub-agent architecture (#165, #167–#173)
- Real-time streaming via Server-Sent Events with search progress indicators
- Multi-turn conversations with thread history (save, rename, search)
- Animated typing dots and improved UX (#197)
- Citation range validation and unauthenticated chat history preservation (#176)
- Config-driven parameters for `max_queries`, `recursion_limit`, and `max_search_results`

### Research Trees (Drilldown Research)
- AI Summary drilldown — highlight text or click "Find out more" to explore sub-topics (#88)
- Tree-based navigation with branching graph view
- Save and load research trees (#135)
- PDF export with global summary (#118)
- Batch research — "Find out more" for all key facts at once

### User Authentication & Permissions
- Full user module with email/password registration and email verification (#101, #111–#116)
- OAuth single sign-on with Google and Microsoft (#178, #183)
- Three authentication modes: `off`, `on_passive`, `on_active` (#121, #188)
- Cookie-based sessions with CSRF protection (#111, #133)
- Account lockout, rate limiting, and brute-force protection (#166)
- Group-based data-source access control with admin panel (#112, #113, #116)
- Domain restriction for registration
- Privacy policy, Terms of Service, and cookie consent (#179, #181, #182)
- Branded email templates for verification and password reset

### User Feedback & Activity
- Star ratings (1–5) on search results, AI summaries, taxonomy tags, and assistant responses (#113, #164)
- Activity logging for search queries, results, and assistant interactions (#113, #164)
- Admin views with search, sort, pagination, and XLSX export
- Anonymous ratings support (#170)

### Security & API Hardening
- OWASP ASVS L2 hardening — secure headers, CSRF, cookie flags, audit logging (#166)
- API key enforcement in all auth modes (#186, #192, #193)
- Admin API key management (#186)
- Swagger UI always enabled with API key auth (#185, #187, #190, #191)
- Remove API key from browser bundle (#133)
- Mandatory `API_SECRET_KEY` (#192)

### Search Enhancements
- Field boosting for countries/organizations in queries (#122)
- Config-driven filter fields with `default_filter_fields` (#122, #139)
- Facet counts now reflect search results (#201)
- Multi-select document table filters (#173)
- Configurable metadata panel fields (#125)

### Documentation
- Built-in documentation area with searchable sidebar and table of contents (#162)
- About, Tech, and Data pages rendered in the doc viewer
- AI Prompts documentation covering Jinja2 templates and group-level overrides
- Terms of Service page (#179)

### Demo & Getting Started
- Interactive demo script with provider selection (Azure/HuggingFace/Google) (#203, #204)
- Guided API key and `.env` configuration
- Host mode (hardware acceleration) and Docker mode support
- Updated README and Getting Started docs with setup instructions

### Pipeline Improvements
- Tagger auto-split for oversized TOC/summary payloads (#86)
- Indexer: truncate oversized chunks to token limit (#87, #109)
- Parser: pypdf fallback for glyph-contaminated PDFs (#108, #160)
- Summarizer: token-aware chunk sizing (#171)
- Scanner: auto-split semicolon multi-value fields (#144)
- Centralized embedding model access via EmbeddingService (#131)
- Coerce list map_field values to strings for PostgreSQL (#199)
- LLM retry with backoff for transient API errors (#107, #137, #138)
- Google Vertex AI support for embeddings and LLMs (#158, #159)
- World Bank datasource with SDG taxonomy and field mapping (#136, #146–#149)

### Infrastructure & CI
- Google Cloud Vertex AI model support (#158)
- Dynamic model combos filtered by indexed models
- CI on release candidate branches (#91)
- Concurrent user login and search tests (#198)
- API auth unit tests (#189)
- Dependency updates (docling, flask, axios, sqlalchemy, and others)

## [1.0.0] - 2025-12-01

Initial release of Evidence Lab with document processing pipeline, hybrid search, AI summaries, heatmapper, and administration tools.
