# Security Policy

This document outlines the security measures, scanning tools, and best practices implemented in the EvidenceLab AI project.

## Table of Contents

- [Reporting Security Vulnerabilities](#reporting-security-vulnerabilities)
- [Security Architecture](#security-architecture)
- [Automated Security Scanning](#automated-security-scanning)
- [Software Bill of Materials (SBOM)](#sbom-job)
- [Dependency Management](#dependency-management)
- [Code Security Measures](#code-security-measures)
- [Container Security](#container-security)
- [API Security](#api-security)
- [Development Security Practices](#development-security-practices)
- [OWASP ASVS L2 Compliance](#owasp-asvs-l2-compliance)

## Reporting Security Vulnerabilities

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do NOT** create a public GitHub issue for security vulnerabilities
2. Email [evidencelab@astrobagel.com](mailto:evidencelab@astrobagel.com) directly with details of the vulnerability
3. Include steps to reproduce the issue
4. Allow reasonable time for the issue to be addressed before public disclosure

We aim to acknowledge security reports within 48 hours and provide a fix timeline within 7 days.

## Security Architecture

### Defense in Depth

The project implements multiple layers of security:

1. **Pre-commit Hooks**: Catch issues before code enters the repository
2. **CI/CD Security Scans**: Automated checks on every push and PR
3. **Dependency Monitoring**: Automated alerts for vulnerable dependencies
4. **Container Scanning**: Vulnerability checks on Docker images
5. **Runtime Protections**: Input validation, CORS restrictions, rate limiting
6. **Request Size Limits**: Body size enforcement at the middleware layer
7. **Error Sanitisation**: Internal details stripped from production responses
8. **Structured Logging**: JSON-formatted audit trail for SIEM ingestion

## Automated Security Scanning

### Pre-commit Hooks

Security-focused pre-commit hooks run on every commit:

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **Bandit** | Python SAST - detects security issues like SQL injection, hardcoded passwords, unsafe deserialization. Runs at MEDIUM+HIGH severity (`-ll`); four checks skipped with documented justifications (B310, B608, B104, B615 — see `.pre-commit-config.yaml`). | `.pre-commit-config.yaml` |
| **Hadolint** | Dockerfile linting - checks for security misconfigurations | `.pre-commit-config.yaml` |
| **detect-secrets** | Prevents accidental credential commits | `.secrets.baseline` |
| **Gitleaks** | Enhanced secret detection with comprehensive regex patterns | `.pre-commit-config.yaml` |

### CI/CD Security Jobs

The GitHub Actions workflow includes dedicated security jobs:

#### `security-scan` Job

| Check | Tool | Description |
|-------|------|-------------|
| Python Dependencies | pip-audit | Scans `requirements.txt`, `ui/backend/requirements.txt`, `requirements.metrics.txt` and `security-requirements.txt` for known vulnerabilities |
| JavaScript Dependencies | npm audit | Scans `package.json` for known vulnerabilities |
| Python SAST | Bandit | Static analysis for security issues (JSON report artifact) |
| Dockerfile Linting | Hadolint | Checks all Dockerfiles for security best practices |
| Secret Scanning | Gitleaks | Scans entire repository for exposed secrets |

#### Which checks block a merge

| Check | Blocks a merge? |
|-------|-----------------|
| Pre-commit hooks in `code-quality` (Bandit, Gitleaks, Hadolint, detect-secrets) | Yes |
| Gitleaks in `security-scan` | Yes |
| Bandit in `security-scan`, high severity, every check on | Yes |
| Trivy on the UI image in `container-scan`, high and critical | Yes |
| Bandit report in `security-scan`, medium and above | No: a report (`bandit-report` artifact) |
| pip-audit, npm audit, Hadolint in `security-scan` | **Not yet: they report and the job carries on** |
| Trivy on the API image in `container-scan` | **Not yet: `exit-code: '0'`** |

The scanners marked "not yet" each report findings on the current dependencies and base images. Each becomes a hard stop in the change that clears its findings. Until then, read their output in the job logs.

#### Pinned actions and scanners

Every action in `.github/workflows/` is pinned to a full commit, with its version in a comment. A version tag can be moved to other code; a commit can't. Dependabot's `github-actions` updates move the pins. The scanners are pinned too: the Python ones in `security-requirements.txt`, Trivy by its `version` input, and `@cyclonedx/cyclonedx-npm` in the `npx` call.

trivy-action needs particular care. In March 2026 its version tags were pushed to code that stole CI secrets ([GHSA-69fq-xp46-6x23](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23)). Pin only to the commit of an immutable release.

#### `container-scan` Job

| Check | Tool | Description |
|-------|------|-------------|
| API Image | Trivy | Scans built Docker image for OS and application vulnerabilities (CRITICAL, HIGH severity) |
| UI Image | Trivy | Scans built Docker image for OS and application vulnerabilities (CRITICAL, HIGH severity) |

The scanned images are the ones production runs and the release workflow publishes: the `runtime` target of `Dockerfile` (API, MCP server and pipeline) and `ui/frontend/Dockerfile.prod` (nginx web interface). They are scanned before any integration tests run.

#### `sbom` Job

Software Bill of Materials (SBOM) generation for supply chain transparency:

| Component | Tool | Output |
|-----------|------|--------|
| Python dependencies | cyclonedx-bom | `sbom-python.json` (CycloneDX format) |
| JavaScript dependencies | @cyclonedx/cyclonedx-npm | `sbom-javascript.json` (CycloneDX format) |

SBOMs are uploaded as CI artifacts on every run, providing a complete inventory of all third-party dependencies for audit and compliance purposes.

#### CI Pipeline Execution Order

Security jobs run in a strict dependency chain to ensure code quality gates pass before more expensive scans:

`code-quality` → `security-scan` → `sbom` + `container-scan` → `tests` + `ui-tests` → `integration-tests`

Pre-commit hooks (Bandit, Gitleaks, Hadolint, detect-secrets) also run as part of the `code-quality` job, ensuring the same checks that run locally are enforced in CI.

### Frontend Security Linting

ESLint plugins provide JavaScript/TypeScript security analysis:

| Plugin | Purpose |
|--------|---------|
| eslint-plugin-security | Detects potential security issues (eval, object injection, etc.) |
| eslint-plugin-sonarjs | Code quality rules that catch security anti-patterns |

## Dependency Management

### Dependabot Configuration

Dependabot (`.github/dependabot.yml`) automatically monitors and creates PRs for:

- **Python (pip)**: Weekly scans of `requirements.txt`
- **JavaScript (npm)**: Weekly scans of `ui/frontend/package.json`
- **Docker**: Weekly scans of base images in all Dockerfiles
- **GitHub Actions**: Weekly scans of action versions

### Dependency Update Policy

- Security updates are prioritized and should be merged promptly
- Major version updates require manual review for breaking changes
- ML libraries (torch, transformers) have major version updates ignored to prevent breaking changes

## Code Security Measures

### Input Validation

#### Path Traversal Protection

The `/file/{file_path}` endpoint implements comprehensive path traversal protection:

- Double URL decoding to catch encoded attacks (`%2e%2e`, `%252e%252e`)
- Null byte rejection
- Path canonicalization using `Path.resolve()`
- Directory containment verification using `relative_to()`
- Explicit file extension whitelist

#### SQL Injection Prevention

All SQL queries use parameterized queries (`%s` placeholders) for user-supplied values. Dynamic SQL fragments that cannot be parameterized (e.g., `ORDER BY` column names, JSONB path expressions) use **whitelist dictionaries** that map user input to hardcoded SQL strings — user input is never interpolated into SQL.

Specific controls:

- **Sort columns**: `sort_by` API parameter is resolved via a `dict.get()` lookup against a hardcoded map; unrecognised values fall back to a safe default
- **Sort direction**: `sort_order` is normalised to a binary `"ASC"` / `"DESC"` choice
- **Taxonomy filters**: JSONB path expressions use `jsonb_path_exists` with the `vars` argument so taxonomy codes are bound as query parameters; the taxonomy key is validated against `_ALLOWED_TAXONOMY_KEYS`
- **Table names**: derived from `config.json` (operator-controlled), never from user input

#### Data Source Validation

API endpoints validate `data_source` parameters against a whitelist loaded from `config.json`, preventing:

- Cache pollution attacks
- Unintended database connections
- Resource exhaustion

### Untrusted Input Shown to Administrators

Anonymous visitors can write ratings (page feedback) and activity rows, and administrators read them in the admin screens and in Excel exports. Three controls keep that input from running in an administrator's browser or spreadsheet:

- **Server-side refusal** (`ui/backend/auth/schemas.py`, ratings and activity payloads): a `data:` URL is accepted only as a PNG, JPEG, WebP or GIF image (an SVG can carry script), and a `javascript:` or `vbscript:` value is refused in any link field (`url`, `link`, `href`, `*_url`). Whitespace and control characters inside the scheme are ignored, as browsers ignore them. Other text is stored as typed, because it is shown as text.
- **Links rendered safely** (`ui/frontend/src/utils/safeHref.ts`): a link that comes from stored data (document metadata, ratings, activity, the research PDF export) is made clickable only for `http`, `https`, `mailto` or a path on this site. Word exports link only to full `http(s)` addresses. Feedback screenshots open full size inside the page, never as a document in a new tab.
- **Spreadsheet cells are text** (`ui/backend/utils/excel_text.py`): every export (ratings, activity, LLM usage, citation check) writes cells that start with `=` as text, so a comment such as `=HYPERLINK(...)` is not a formula when the file is opened.

### CORS Configuration

CORS is configured securely:

- **Origins**: Read from `CORS_ALLOWED_ORIGINS` environment variable; defaults to localhost for development (never `*`)
- **Headers**: Read from `CORS_ALLOWED_HEADERS` environment variable; defaults to `Content-Type, Authorization, X-API-Key, X-CSRF-Token, Accept, Accept-Language` (never `*`)
- Explicit HTTP method whitelist (`GET, POST, PUT, PATCH, DELETE, OPTIONS`)
- Credentials supported only for allowed origins

### Request Body Size Limits

Request body size is enforced at the middleware layer (ASVS V13.1.3):

- Requests with `Content-Length` exceeding the limit are rejected with HTTP 413
- Default limit: 2 MB; configurable via `MAX_REQUEST_BODY_BYTES` env var
- GET and other bodyless requests are unaffected

### Error Detail Sanitisation

Production error responses never expose internal details (ASVS V7.1.1, V7.4.1):

- `ValueError` responses return a generic message unless the error matches a known-safe prefix (e.g. `"Invalid data_source:"`)
- Unhandled exceptions return `"Internal server error"` with no stack traces, paths, or internal state
- Full details available when `API_DEBUG=true` (development only)
- Full tracebacks are always logged server-side regardless of debug mode

### Structured Logging

JSON-structured log output for SIEM integration (ASVS V7.1.3):

- `JSONLogFormatter` outputs `{timestamp, level, logger, message, module, function, line}` with UTC ISO 8601 timestamps
- Security-relevant extra fields (`user_id`, `user_email`, `ip_address`, `event_type`, `request_id`) included when present
- Exception tracebacks included in the `exception` field
- Enabled via `LOG_FORMAT=json` env var; plain text remains the default

### Rate Limiting

API endpoints are protected by rate limiting (slowapi):

- Search operations: Configurable via `RATE_LIMIT_SEARCH`
- AI operations: Configurable via `RATE_LIMIT_AI`
- Default operations: Configurable via `RATE_LIMIT_DEFAULT`

### API Key Authentication

- API key authentication via `X-API-Key` header
- Timing-safe comparison using `secrets.compare_digest()`
- OpenAPI/Swagger docs (`/docs`, `/redoc`, `/openapi.json`) are served in every deployment and need no key

## Container Security

### Dockerfile Best Practices

Hadolint enforces:

- Avoiding `latest` tags for base images
- Minimizing layer count
- Using specific package versions where practical
- Multi-stage builds to reduce attack surface

**Ignored rules**: `DL3008` (pin apt versions), `DL3013` (pin pip versions), `DL3042` (pip cache) — suppressed because ML dependencies require flexible version resolution and pip caching improves build times.

### Image Scanning

Trivy scans Docker images for:

- OS package vulnerabilities
- Application dependency vulnerabilities
- Misconfigurations

Scans are configured for CRITICAL and HIGH severity. Results appear in the `container-scan` job log; they are not yet uploaded to GitHub Security and do not fail the build (see [Which checks block a merge](#which-checks-block-a-merge)).

## API Security

### API Key Authentication

- API key required for all endpoints except `/health`, `/auth/*`, `/users/*`, `/groups/*`, `/ratings/*`, `/activity/*`, `/api-keys`, file serving (`/file/*`, `/pdf/*`), `/document/{id}/thumbnail` and the OpenAPI docs
- Exempt paths are matched by whole path segment: `/docs` covers `/docs` and `/docs/...` but not `/docsearch`
- API key validated using timing-safe comparison
- With the user module on, a request without a key is let through only if its `evidencelab_auth` cookie is a valid session token (signature, audience and expiry are checked). A cookie that is merely present is not enough.
- The key built into the web interface (`REACT_APP_API_KEY`) is public: anyone who loads the site can read it. The API accepts it when sign-in is off or optional, so the open demo works; it is ignored as a credential when sign-in is required (`on_active`), in both the API-key check and the middleware; and MCP and A2A never accept it, even when it is also `API_SECRET_KEY`. Give it its own value so the master key stays private. The API logs a warning at startup when the two are the same.
- Auth routes exempt from API key — protected by their own rate-limiting and CSRF
- With `on_passive` or `off`, the browser build carries the API key (`REACT_APP_API_KEY`), so anyone who loads the site can read it. Treat routes that rely on the key alone as public, and protect anything that changes data with a user check (see [Authorization](#authorization)).

### User Authentication Module

When `USER_MODULE` is set to `on_passive` or `on_active`, fastapi-users provides full user lifecycle management. In `on_passive` mode, authentication is optional and anonymous users can browse freely. In `on_active` mode, all access requires login:

| Control | Implementation |
|---------|---------------|
| **Token storage** | httpOnly cookies only; no localStorage (XSS mitigation) |
| **Token lifetime** | 1-hour JWTs for access; separate configurable lifetimes for reset (24h) and verify (7d) tokens |
| **Cookie flags** | `httponly`, `secure`, `samesite=lax` |
| **CSRF protection** | Double-submit cookie (`evidencelab_csrf` + `X-CSRF-Token` header); cookie cleared on logout/account deletion |
| **Secret validation** | `AUTH_SECRET_KEY` must be 32+ chars; insecure defaults rejected |
| **Input validation** | `display_name` max 255 chars, whitespace-stripped, blank-to-None |
| **Password policy** | Minimum length only (configurable via `AUTH_MIN_PASSWORD_LENGTH`); no character-class or breached-password check |
| **Password history** | Prevents reuse of last N passwords; configurable via `AUTH_PASSWORD_HISTORY_COUNT` (default 5, ASVS V2.1.10) |
| **Account lockout** | Lock after N consecutive failures for M minutes; counters reset on password reset (`AUTH_LOCKOUT_THRESHOLD`, `AUTH_LOCKOUT_DURATION_MINUTES`) |
| **Timing-attack mitigation** | Password hash always computed even for non-existent users |
| **Registration control** | Email domain whitelist via `AUTH_ALLOWED_EMAIL_DOMAINS` (registration only; not enforced on password change) |
| **Rate limiting** | Per-IP sliding window on `/auth/*` (default 10 req/60s) |
| **Permission model** | Deny-by-default; unauthenticated users see no datasources |
| **Error handling** | Permission failures logged and return empty data (no leak) |
| **Audit logging** | All auth events (login, failure, lockout, register, password reset) logged to `audit_log` table |
| **OAuth** | Google and Microsoft SSO with explicit minimal scopes (`openid, email, profile`); callers cannot ask for others. Each sign-in is bound to the browser that started it: `/authorize` sets an httpOnly, SameSite=Lax cookie, scoped to the callback path, holding a PKCE code verifier, and the signed state (10-minute lifetime) carries its S256 challenge. `/callback` refuses unless the state is valid and matches the cookie (constant-time comparison), then sends the verifier with the code so the provider checks it too |
| **Email verification** | Required after registration; token sent via SMTP |

### Active Authentication Enforcement (`on_active` mode)

When `USER_MODULE_MODE=on_active`, the `ActiveAuthMiddleware` enforces authentication on **all data endpoints** at the middleware layer. This ensures that no data endpoint can be accessed without valid credentials, even if an individual route handler lacks its own auth dependency.

#### How It Works

The middleware intercepts every incoming request and validates credentials before the request reaches any route handler. It checks (in order):

1. **API key** — `X-API-Key` header compared against `API_SECRET_KEY` using `secrets.compare_digest()` (timing-safe)
2. **Bearer token** — `Authorization: Bearer <jwt>` header decoded with HS256 and audience `["fastapi-users:auth"]`
3. **Session cookie** — `evidencelab_auth` httpOnly cookie decoded with the same JWT secret and audience

If none of the above yield a valid credential, the middleware returns `401 {"detail": "Authentication required"}` without forwarding the request.

#### Exempt Paths

The following paths are exempt from middleware authentication because they either have their own auth mechanisms or must be publicly accessible. A prefix covers the path itself and paths beneath it, matched by whole segment, so `/docs` does not exempt `/docsearch`:

| Path prefix | Reason |
|-------------|--------|
| `/health` | Health check endpoint (monitoring/load balancer probes) |
| `/auth/` | Login, register, verify, password reset — has own auth flow |
| `/config/auth-status` | Frontend feature flag (must be accessible before login) |
| `/users/` | Protected by fastapi-users `current_active_user` dependency |
| `/groups/` | Protected by fastapi-users `current_active_user` dependency |
| `/ratings/` | Protected by fastapi-users `current_active_user` dependency |
| `/activity/` | Protected by fastapi-users `current_active_user` dependency |
| `/api-keys` | Protected by fastapi-users `current_superuser` dependency |
| `/docs`, `/redoc`, `/openapi.json` | OpenAPI docs (served in every deployment) |
| `OPTIONS` | CORS preflight requests |

#### Security Properties

| Property | Detail |
|----------|--------|
| **Scope** | Only active when `USER_MODULE_MODE == "on_active"` |
| **Layer** | Starlette middleware — runs before all route handlers |
| **JWT validation** | Verifies signature, expiry, and audience claim |
| **API key comparison** | Timing-safe via `secrets.compare_digest()` |
| **Fail-closed** | Denies by default; only permits explicitly validated credentials |
| **Logging** | Denied requests logged with method, path, and client IP |
| **Test coverage** | 23 dedicated unit tests covering all auth paths and edge cases |

#### Relationship to Other Auth Controls

The middleware provides **defense in depth** alongside existing controls:

- **`/config/datasources`** — already denies unauthenticated users (returns empty list); the middleware adds a hard 401 for all other data endpoints
- **fastapi-users routes** (`/users/`, `/groups/`, etc.) — have their own `Depends(current_active_user)` checks; the middleware exempts these to avoid double-validation
- **API key auth** — the middleware accepts the same `API_SECRET_KEY` used elsewhere, so programmatic API access continues to work
- **Frontend login wall** — `AuthGate` component blocks UI access; the middleware ensures the same protection at the API layer

### Authorization

- Data source access controlled via whitelist validation and group-based RBAC
- File serving restricted to specific directories and file types
- Superusers bypass datasource filtering; regular users see only granted sources
- Changing documents and running the pipeline require a signed-in superuser: editing a document's contents (`PUT /document/{id}/toc`), its metadata (`PATCH /documents/{id}`), reprocessing (`POST /documents/{id}/reprocess`, `POST /documents/{id}/reprocess-toc`), the queue status (`GET /queue/status`) and processing logs (`GET /document/{id}/logs`). The API key alone is not enough, and without the user module these routes always refuse. The UI shows these controls only to superusers.

### Security Headers

Application-level security headers middleware provides defence-in-depth:

- `Content-Security-Policy` — configurable via `CSP_POLICY` env var; defaults to strict self-only policy with `frame-ancestors 'none'`, SHA-256 hash-based inline script allowlisting (no `'unsafe-inline'` in `script-src`), and explicit `connect-src` for analytics domains
- `X-Content-Type-Options: nosniff` — prevents MIME-sniffing
- `X-Frame-Options: DENY` — prevents clickjacking
- `Referrer-Policy: strict-origin-when-cross-origin` — limits referrer leakage
- `Permissions-Policy` — restricts camera, microphone, geolocation
- `Strict-Transport-Security` — HSTS with `preload` directive when HTTPS is configured; warning logged when `AUTH_COOKIE_SECURE=false`
- `Cache-Control: no-store` + `Pragma: no-cache` on sensitive endpoints (`/auth/`, `/users/`, `/groups/`, `/ratings/`, `/activity/`) — prevents browsers and proxies from caching tokens or personal data (ASVS V8.1.4)

These headers are added by the API to its own responses. The web pages and static files are served by nginx (`ui/frontend/nginx.conf`), which sets its own headers from one file, `ui/frontend/nginx-security-headers.conf`: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`, and a `Content-Security-Policy`. nginx drops server-level headers for any `location` that sets an `add_header` of its own, so every such location includes the file again; `tests/unit/test_nginx_security_headers.py` fails if one does not.

The pages' `Content-Security-Policy` is filled in when the ui container starts (`ui/frontend/render-nginx-conf.sh`), from `UI_CSP_POLICY` or this default:

```
default-src 'self'; script-src 'self' https://*.googletagmanager.com; style-src 'self' 'unsafe-inline';
img-src 'self' data: https:; font-src 'self'; connect-src 'self' https://*.google-analytics.com
https://*.analytics.google.com https://*.googletagmanager.com; worker-src 'self';
frame-ancestors 'none'; object-src 'none'; base-uri 'self'
```

- Scripts and workers come from the site only. Google Analytics is the exception, and the app loads it only when it is configured and the visitor accepts analytics cookies.
- There is no inline script and no `eval`: the production build keeps Create React App's runtime as a file (`INLINE_RUNTIME_CHUNK=false`).
- The PDF viewer loads PDF.js from the site. `scripts/copy-pdfjs.js` copies it from the `pdfjs-dist` version in `package-lock.json` into the build at `/pdfjs/<version>/`.
- PDF.js runs without WebAssembly (`useWasm: false`, using its JavaScript image decoders), so the policy needs no `'wasm-unsafe-eval'`.
- The app's typefaces (Poppins and Open Sans) are bundled from `@fontsource` and served from the site, not loaded from Google Fonts, so `style-src` and `font-src` need no outside address and visitors' browsers do not contact Google for them.
- Styles allow inline, because React and the MCP consent page set style attributes.
- `form-action` is left out: it does not fall back to `default-src`, and the MCP consent form's answer redirects to the MCP client's own address.
- A deployment that loads other outside assets sets `UI_CSP_POLICY`. The container refuses a value with a line break or any of `| & \ " $`.

Production deployments via Caddy additionally include:

- Automatic HTTPS with Let's Encrypt
- API key validation for protected endpoints
- Proper proxy headers (X-Real-IP, X-Forwarded-For, X-Forwarded-Proto)

## Development Security Practices

### Environment Variables

- Sensitive values stored in `.env` files (gitignored)
- `.env.example` provides templates without real values
- Secrets managed via GitHub Actions secrets for CI/CD
- `AUTH_SECRET_KEY` is **required** in production — Docker Compose uses `:?` syntax to fail-fast if unset; startup logs a CRITICAL warning for insecure or short values (ASVS V14.1.2)

### Secret Management

- `detect-secrets` baseline prevents new secrets from being committed
- Gitleaks provides additional coverage with comprehensive patterns (configured in `gitleaks.toml`)
- Pre-commit hooks catch secrets before they enter git history

### Secure Coding Guidelines

1. **Never hardcode secrets** - Use environment variables
2. **Validate all input** - Especially file paths and user-provided data
3. **Use parameterized queries** - Prevent SQL injection
4. **Avoid dangerous functions** - `eval()`, `exec()`, `subprocess` with `shell=True`
5. **Keep dependencies updated** - Review Dependabot PRs promptly
6. **Follow least privilege** - Containers and services should have minimal permissions

## OWASP ASVS L2 Compliance

The project targets OWASP ASVS Level 2 compliance. Current estimated coverage is **~82%** across the 14 ASVS verification categories. Key controls mapped to ASVS requirements:

| ASVS Requirement | Control | Status |
|------------------|---------|--------|
| V2.1.10 | Password history / reuse prevention | Done |
| V7.1.1, V7.4.1 | Error detail sanitisation | Done |
| V7.1.3 | Structured JSON logging | Done |
| V8.1.4 | Sensitive endpoint cache control | Done |
| V13.1.3 | Request body size limits | Done |
| V14.1.2 | Startup credential validation | Done |
| V14.4.3 | CSP with hash-based inline scripts | Done |

## Security Checklist for Contributors

Before submitting a PR, ensure:

- [ ] No hardcoded secrets or credentials
- [ ] Input validation for user-provided data
- [ ] All SQL uses parameterized queries — no f-string/format interpolation of user input
- [ ] Dynamic SQL fragments (ORDER BY, JSONB paths) use whitelist lookups, not interpolation
- [ ] Pre-commit hooks pass (including Bandit, Gitleaks)
- [ ] No new security warnings in CI
- [ ] Sensitive operations are properly authenticated
- [ ] File operations validate paths against allowed directories

## Cryptographic Algorithms

### Algorithms in Use

| Mechanism | Algorithm | Notes |
|-----------|-----------|-------|
| Transport (HTTPS) | TLS 1.2/1.3, AEAD ciphers only (AES-GCM, ChaCha20-Poly1305) | Enforced in Caddyfile; TLS 1.0/1.1 disabled |
| Password hashing | bcrypt (work factor 12, via fastapi-users) | Adaptive, salted |
| JWT signing | HS256 (HMAC-SHA256) | 256-bit secret, minimum 32 chars enforced at startup |
| API key storage | SHA-256 (first 8 hex chars stored for audit; full hash for lookup) | One-way |
| API key encryption at rest | Fernet (AES-128-CBC + HMAC-SHA256) | See note below |
| CSRF token comparison | `secrets.compare_digest` (constant-time) | stdlib |
| OAuth 2.0 | Authorization code flow with PKCE (S256) via httpx-oauth; state is a signed JWT bound to a browser cookie | No custom crypto |

### Note on Fernet (AES-128-CBC)

API key values are encrypted at rest using Python's `cryptography.fernet.Fernet`. Fernet internally uses AES-128 in CBC mode. Although CBC mode has known weaknesses in unauthenticated constructions (e.g., padding oracle attacks in older SSH and TLS implementations), Fernet is not vulnerable to these because it applies **Encrypt-then-MAC** (HMAC-SHA256 over the full ciphertext) with a fresh random 128-bit IV per message. This construction is cryptographically sound and is the pattern recommended by the Python `cryptography` library for symmetric encryption at rest.

This use of CBC is distinct from the weakness cited in the OpenSSF criterion ("CBC mode in SSH"), which refers to unauthenticated CBC. The HMAC-SHA256 authentication tag in Fernet prevents all known CBC-mode attacks. No plaintext CBC is used anywhere in the project.

### Algorithms Explicitly Not Used

MD4, MD5 (for security purposes), RC4, single DES, 3DES, SHA-1 (for security purposes), unauthenticated CBC, ECB, Dual_EC_DRBG. MD5 and SHA-1 appear in maintenance scripts only as non-cryptographic file-change detectors, explicitly flagged `usedforsecurity=False`.

## Tools Reference

| Tool | Purpose | Documentation |
|------|---------|---------------|
| Bandit | Python SAST | https://bandit.readthedocs.io/ |
| Hadolint | Dockerfile linting | https://github.com/hadolint/hadolint |
| detect-secrets | Secret detection | https://github.com/Yelp/detect-secrets |
| Gitleaks | Secret detection | https://github.com/gitleaks/gitleaks |
| pip-audit | Python dependency scanning | https://github.com/pypa/pip-audit |
| npm audit | JS dependency scanning | https://docs.npmjs.com/cli/v8/commands/npm-audit |
| Trivy | Container scanning | https://aquasecurity.github.io/trivy/ |
| cyclonedx-bom | Python SBOM generation | https://github.com/CycloneDX/cyclonedx-python |
| @cyclonedx/cyclonedx-npm | JavaScript SBOM generation | https://github.com/CycloneDX/cyclonedx-node-npm |
| eslint-plugin-security | JS security linting | https://github.com/eslint-community/eslint-plugin-security |

## Changelog

- **2026-11-23**: Serve PDF.js from the site and restrict the pages' scripts
  - The PDF viewer loads PDF.js 6.5.438 from the site instead of cdnjs (3.11.174); the version comes from `package-lock.json`
  - The web pages' `Content-Security-Policy` now restricts scripts, styles, images, fonts, connections and workers, configurable per deployment with `UI_CSP_POLICY`
  - The production build has no inline script (`INLINE_RUNTIME_CHUNK=false`)
  - The typefaces are served from the site instead of Google Fonts
- **2026-11-17**: Tighten API access checks and page headers
  - Document write and pipeline routes (contents and metadata edits, reprocessing, queue status, processing logs) now require a signed-in superuser instead of the API key alone; the UI shows those controls only to superusers
  - The API-key check now verifies the session cookie's token instead of accepting any cookie value
  - Exempt paths in the API-key check and the `on_active` middleware are matched by whole path segment through one shared helper (`ui/backend/auth/request_checks.py`)
  - `reprocess-toc` checks the data source against `config.json` before queueing
  - nginx now sends the security headers, plus HSTS and a framing/plugin CSP, on the web pages and static files; they were missing because locations with their own `add_header` dropped the server-level ones
  - Corrected this file where it did not match the code: CI dependency and image scans report but do not block, Trivy results are not uploaded as SARIF, the OpenAPI docs are served in every deployment, and the password policy checks length only
- **2026-11-17**: Keep anonymous input from running in admin screens and exports
  - Ratings and activity payloads refuse non-raster `data:` URLs and `javascript:`/`vbscript:` link values
  - Admin screens and the research PDF export render links from stored data only for `http`, `https`, `mailto` and site paths; Word exports link only to `http(s)` addresses
  - Feedback screenshots open full size in the page instead of a new tab
  - Spreadsheet exports write formula-looking cells as text
- **2026-11-17**: The web interface's public key no longer opens MCP, A2A or sign-in-required mode
  - MCP and A2A refuse `REACT_APP_API_KEY`, even when it is also `API_SECRET_KEY` or an admin-created key; signed-in users and other keys still work
  - With `on_active`, the API-key check and the middleware ignore that key as a credential
  - The API accepts a `REACT_APP_API_KEY` that differs from `API_SECRET_KEY`, so the two can be separated; the demo, CI and dev compose now use separate values, and the API warns at startup when they are the same
- **2026-11-17**: MCP sign-in asks for consent and is tied to the browser that started it
  - `/mcp/authorize` sets a short-lived, httpOnly cookie in the starting browser; `/mcp/complete` refuses any other browser, so a link to someone else's request cannot connect their app to your account
  - `/mcp/complete` shows which client is asking and where it will be sent; the answer is a same-origin POST with a one-time token, and denying returns `error=access_denied`
  - MCP access tokens carry their own audience (`evidencelab:mcp`): MCP and A2A accept them, the web app does not; only a web sign-in session can answer the consent page
- **2026-11-17**: Limit what one request can cost
  - AI routes (AI summary, assistant, highlight, Brief outline and revise) accept only a model listed in `config.json`, and at most the output tokens `config.json` sets for it (`ui/backend/utils/llm_request_limits.py`)
  - Search `limit` is capped by `SEARCH_MAX_LIMIT` (default 10000) and highlight text by `HIGHLIGHT_MAX_TEXT_CHARS` (default 50000)
  - The MCP and A2A rate limits (`RATE_LIMIT_MCP_SEARCH`, `RATE_LIMIT_MCP_AI`), documented but never applied, are now enforced per caller (signed-in user or API key) rather than per client address

- **2026-04-12**: Fix SQL injection via `sort_by` and taxonomy filter parameters (#264)
  - Replaced f-string interpolation of `sort_by` in `ORDER BY` clause with a whitelist dictionary lookup (hardcoded SQL fragments only)
  - Replaced f-string interpolation of taxonomy codes in `jsonb_path_exists` with parameterized `vars` argument (`jsonb_build_object('v', %s::text)`)
  - Added `_ALLOWED_TAXONOMY_KEYS` frozenset to validate taxonomy keys before use in JSONB path expressions
  - Added "SQL Injection Prevention" section to SECURITY.md documenting all controls
  - Added 15 regression tests covering injection attempts, whitelist fallback, and parameterisation
- **2026-03-31**: Document cryptographic algorithms (OpenSSF Best Practices)
  - Added "Cryptographic Algorithms" section listing all algorithms in use
  - Documented Fernet (AES-128-CBC + HMAC-SHA256) Encrypt-then-MAC construction and why it is not vulnerable to known CBC-mode attacks
  - Documented algorithms explicitly not used (MD5, RC4, SHA-1, unauthenticated CBC, ECB, etc.)
- **2026-03-30**: Bandit upgrade and severity threshold increase
  - Upgraded Bandit from 1.7.7 to 1.9.4 (latest)
  - Raised threshold from HIGH-only (`-lll`) to MEDIUM+HIGH (`-ll`)
  - Fixed B310 (urlopen scheme audit): added explicit `https://` / `http://` scheme validation in `azure_foundry_reranker.py` and `search_models.py` before calling `urlopen()`
  - Documented four globally-skipped checks with justifications in `.pre-commit-config.yaml`: B310 (scheme validated in code), B608 (table names from config, not user input), B104 (intentional 0.0.0.0 bind), B615 (model ID from operator config)
- **2026-03-10**: ASVS L2 Tier 1 + Tier 2 hardening (33 new tests)
  - Added request body size limit middleware — rejects >2 MB with HTTP 413 (`MAX_REQUEST_BODY_BYTES`, ASVS V13.1.3)
  - Added error detail sanitisation — production responses never expose internals (`API_DEBUG`, ASVS V7.1.1 / V7.4.1)
  - Added startup credential validation — CRITICAL log on insecure `AUTH_SECRET_KEY`; Docker Compose fails-fast if unset (ASVS V14.1.2)
  - Hardened CSP with SHA-256 hash for inline GA script — removed need for `'unsafe-inline'` in `script-src` (ASVS V14.4.3)
  - Added structured JSON logging via `LOG_FORMAT=json` for SIEM ingestion (ASVS V7.1.3)
  - Added password history — prevents reuse of last N passwords (`AUTH_PASSWORD_HISTORY_COUNT`, ASVS V2.1.10)
  - Added Alembic migration `0016_add_password_history` (nullable JSONB column)
  - Added `Cache-Control: no-store` on sensitive endpoint responses (ASVS V8.1.4)
- **2026-03-03**: Active authentication enforcement middleware
  - Added `ActiveAuthMiddleware` for `on_active` mode — denies unauthenticated requests to all data endpoints
  - Middleware validates JWT cookies, Bearer tokens, and API keys at the Starlette layer (before route handlers)
  - Fail-closed design: denies by default, only permits explicitly validated credentials
  - Exempt paths for health checks, auth flows, and routes with their own fastapi-users dependencies
  - Frontend `AuthGate` component enforces login wall in the UI for `on_active` mode
  - 23 dedicated unit tests covering all auth paths, exempt routes, and edge cases
- **2026-03-01**: Security hardening for enterprise pen testing
  - Added Content-Security-Policy header (env-configurable via `CSP_POLICY`)
  - Changed CORS `allow_headers` from `*` to env-configurable whitelist (`CORS_ALLOWED_HEADERS`)
  - Added `display_name` input validation (max 255 chars, whitespace stripping)
  - Moved email domain whitelist check to registration only (no longer triggers on password change)
  - Added lockout counter reset on successful password reset
  - Separated token lifetimes: reset tokens (24h) and verification tokens (7d) independently configurable
  - Added warning log when no default group is configured for new users
  - Added CSRF cookie clearing on account deletion
  - Added explicit minimal OAuth scopes (`openid, email, profile`) for Google and Microsoft
  - Added HSTS `preload` directive for HSTS preload list eligibility
  - Added warning log when `AUTH_COOKIE_SECURE` is disabled (HTTP-only development)
- **2026-03-01**: User authentication & permissions module
  - Added cookie-based JWT auth with httpOnly, secure, samesite=lax flags
  - Added CSRF double-submit cookie middleware (`evidencelab_csrf`)
  - Added security response headers middleware (X-Content-Type-Options, X-Frame-Options, etc.)
  - Added per-IP rate limiting on auth endpoints (sliding window)
  - Added account lockout with timing-attack mitigation
  - Added password complexity validation (length + digit + letter)
  - Added email domain whitelisting for registration
  - Added immutable audit log table for all auth events
  - Added group-based RBAC with deny-by-default datasource permissions
  - Added Google and Microsoft OAuth2 SSO support
  - Exempted `/auth/*` routes from API key requirement
- **2026-02-05**: Comprehensive security policy
  - Added Bandit for Python SAST
  - Added Hadolint for Dockerfile linting
  - Added Gitleaks for enhanced secret detection
  - Added eslint-plugin-security for frontend
  - Added pip-audit and npm audit to CI
  - Added Trivy container scanning
  - Configured Dependabot for automated updates
  - Fixed CORS misconfiguration
  - Fixed path traversal vulnerability
  - Added data source validation
