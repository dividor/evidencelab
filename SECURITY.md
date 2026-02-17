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

- Origins read from `CORS_ALLOWED_ORIGINS` environment variable
- Defaults to localhost for development (not `*`)
- Explicit HTTP method whitelist
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

### Authentication

- API key required for all endpoints except `/health`
- API key validated using timing-safe comparison
- Development mode allows unauthenticated access (no `API_SECRET_KEY` set)

### Authorization

- Data source access controlled via whitelist validation
- File serving restricted to specific directories and file types

### Security Headers

Production deployments via Caddy include:

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
