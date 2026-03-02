# Security Policy

This document outlines the security measures, scanning tools, and best practices implemented in the EvidenceLab AI project.

## Table of Contents

- [Reporting Security Vulnerabilities](#reporting-security-vulnerabilities)
- [Security Architecture](#security-architecture)
- [Automated Security Scanning](#automated-security-scanning)
- [Dependency Management](#dependency-management)
- [Code Security Measures](#code-security-measures)
- [Container Security](#container-security)
- [API Security](#api-security)
- [Development Security Practices](#development-security-practices)

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

## Automated Security Scanning

### Pre-commit Hooks

Security-focused pre-commit hooks run on every commit:

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **Bandit** | Python SAST - detects security issues like SQL injection, hardcoded passwords, unsafe deserialization | `.pre-commit-config.yaml` |
| **Hadolint** | Dockerfile linting - checks for security misconfigurations | `.pre-commit-config.yaml` |
| **detect-secrets** | Prevents accidental credential commits | `.secrets.baseline` |
| **Gitleaks** | Enhanced secret detection with comprehensive regex patterns | `.pre-commit-config.yaml` |

### CI/CD Security Jobs

The GitHub Actions workflow includes dedicated security jobs:

#### `security-scan` Job

| Check | Tool | Description |
|-------|------|-------------|
| Python Dependencies | pip-audit | Scans `requirements.txt` for known vulnerabilities |
| JavaScript Dependencies | npm audit | Scans `package.json` for known vulnerabilities |
| Python SAST | Bandit | Static analysis for security issues (JSON report artifact) |
| Dockerfile Linting | Hadolint | Checks all Dockerfiles for security best practices |
| Secret Scanning | Gitleaks | Scans entire repository for exposed secrets |

#### `container-scan` Job

| Check | Tool | Description |
|-------|------|-------------|
| API Image | Trivy | Scans built Docker image for OS and application vulnerabilities |
| UI Image | Trivy | Scans built Docker image for OS and application vulnerabilities |

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

#### Data Source Validation

API endpoints validate `data_source` parameters against a whitelist loaded from `config.json`, preventing:

- Cache pollution attacks
- Unintended database connections
- Resource exhaustion

### CORS Configuration

CORS is configured securely:

- **Origins**: Read from `CORS_ALLOWED_ORIGINS` environment variable; defaults to localhost for development (never `*`)
- **Headers**: Read from `CORS_ALLOWED_HEADERS` environment variable; defaults to `Content-Type, Authorization, X-API-Key, X-CSRF-Token, Accept, Accept-Language` (never `*`)
- Explicit HTTP method whitelist (`GET, POST, PUT, PATCH, DELETE, OPTIONS`)
- Credentials supported only for allowed origins

### Rate Limiting

API endpoints are protected by rate limiting (slowapi):

- Search operations: Configurable via `RATE_LIMIT_SEARCH`
- AI operations: Configurable via `RATE_LIMIT_AI`
- Default operations: Configurable via `RATE_LIMIT_DEFAULT`

### API Key Authentication

- API key authentication via `X-API-Key` header
- Timing-safe comparison using `secrets.compare_digest()`
- OpenAPI/Swagger docs disabled in production

## Container Security

### Dockerfile Best Practices

Hadolint enforces:

- Avoiding `latest` tags for base images
- Minimizing layer count
- Using specific package versions where practical
- Multi-stage builds to reduce attack surface

### Image Scanning

Trivy scans Docker images for:

- OS package vulnerabilities
- Application dependency vulnerabilities
- Misconfigurations

## API Security

### API Key Authentication

- API key required for all endpoints except `/health`, `/auth/*`, file serving
- API key validated using timing-safe comparison
- Auth routes exempt from API key — protected by their own rate-limiting and CSRF
- Development mode allows unauthenticated access (no `API_SECRET_KEY` set)

### User Authentication Module

When `USER_MODULE=true`, fastapi-users provides full user lifecycle management:

| Control | Implementation |
|---------|---------------|
| **Token storage** | httpOnly cookies only; no localStorage (XSS mitigation) |
| **Token lifetime** | 1-hour JWTs for access; separate configurable lifetimes for reset (24h) and verify (7d) tokens |
| **Cookie flags** | `httponly`, `secure`, `samesite=lax` |
| **CSRF protection** | Double-submit cookie (`evidencelab_csrf` + `X-CSRF-Token` header); cookie cleared on logout/account deletion |
| **Secret validation** | `AUTH_SECRET_KEY` must be 32+ chars; insecure defaults rejected |
| **Input validation** | `display_name` max 255 chars, whitespace-stripped, blank-to-None |
| **Password policy** | Minimum length + digit + letter (configurable via `AUTH_MIN_PASSWORD_LENGTH`) |
| **Account lockout** | Lock after N consecutive failures for M minutes; counters reset on password reset (`AUTH_LOCKOUT_THRESHOLD`, `AUTH_LOCKOUT_DURATION_MINUTES`) |
| **Timing-attack mitigation** | Password hash always computed even for non-existent users |
| **Registration control** | Email domain whitelist via `AUTH_ALLOWED_EMAIL_DOMAINS` (registration only; not enforced on password change) |
| **Rate limiting** | Per-IP sliding window on `/auth/*` (default 10 req/60s) |
| **Permission model** | Deny-by-default; unauthenticated users see no datasources |
| **Error handling** | Permission failures logged and return empty data (no leak) |
| **Audit logging** | All auth events (login, failure, lockout, register, password reset) logged to `audit_log` table |
| **OAuth** | Google and Microsoft SSO with explicit minimal scopes (`openid, email, profile`) |
| **Email verification** | Required after registration; token sent via SMTP |

### Authorization

- Data source access controlled via whitelist validation and group-based RBAC
- File serving restricted to specific directories and file types
- Superusers bypass datasource filtering; regular users see only granted sources

### Security Headers

Application-level security headers middleware provides defence-in-depth:

- `Content-Security-Policy` — configurable via `CSP_POLICY` env var; defaults to strict self-only policy with `frame-ancestors 'none'`
- `X-Content-Type-Options: nosniff` — prevents MIME-sniffing
- `X-Frame-Options: DENY` — prevents clickjacking
- `Referrer-Policy: strict-origin-when-cross-origin` — limits referrer leakage
- `Permissions-Policy` — restricts camera, microphone, geolocation
- `Strict-Transport-Security` — HSTS with `preload` directive when HTTPS is configured; warning logged when `AUTH_COOKIE_SECURE=false`

Production deployments via Caddy additionally include:

- Automatic HTTPS with Let's Encrypt
- API key validation for protected endpoints
- Proper proxy headers (X-Real-IP, X-Forwarded-For, X-Forwarded-Proto)

## Development Security Practices

### Environment Variables

- Sensitive values stored in `.env` files (gitignored)
- `.env.example` provides templates without real values
- Secrets managed via GitHub Actions secrets for CI/CD

### Secret Management

- `detect-secrets` baseline prevents new secrets from being committed
- Gitleaks provides additional coverage with comprehensive patterns
- Pre-commit hooks catch secrets before they enter git history

### Secure Coding Guidelines

1. **Never hardcode secrets** - Use environment variables
2. **Validate all input** - Especially file paths and user-provided data
3. **Use parameterized queries** - Prevent SQL injection
4. **Avoid dangerous functions** - `eval()`, `exec()`, `subprocess` with `shell=True`
5. **Keep dependencies updated** - Review Dependabot PRs promptly
6. **Follow least privilege** - Containers and services should have minimal permissions

## Security Checklist for Contributors

Before submitting a PR, ensure:

- [ ] No hardcoded secrets or credentials
- [ ] Input validation for user-provided data
- [ ] Pre-commit hooks pass (including Bandit, Gitleaks)
- [ ] No new security warnings in CI
- [ ] Sensitive operations are properly authenticated
- [ ] File operations validate paths against allowed directories

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
| eslint-plugin-security | JS security linting | https://github.com/eslint-community/eslint-plugin-security |

## Changelog

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
