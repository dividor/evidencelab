# Contributing to Humanitarian Evaluation AI Research Pipeline

Thank you for your interest in contributing to the Humanitarian Evaluation AI Research Pipeline! This document provides guidelines and instructions for contributing to the project.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Pre-commit Hooks](#pre-commit-hooks)
- [Security](#security)
- [Making Changes](#making-changes)
- [Commit Guidelines](#commit-guidelines)
- [Testing](#testing)
- [Evaluation](#evaluation)
- [Performance Tests](#performance-tests)
- [GitHub Actions (CI)](#github-actions-ci)
- [Pull Request Process](#pull-request-process)
- [Issue Guidelines](#issue-guidelines)
- [Code Style](#code-style)

## 🤝 Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please treat all community members with respect and create a welcoming environment for everyone.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before contributing to ensure a positive and inclusive community experience.

## 🚀 Getting Started

### Prerequisites

- Python 3.11 or higher
- Git
- A GitHub account

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/evidencelab-ai.git
   cd evidencelab-ai
   ```
3. Add the upstream repository:
   ```bash
   git remote add upstream https://github.com/ORIGINAL-OWNER/evidencelab-ai.git
   ```

## 💻 Development Setup

See main README.

## 🔧 Pre-commit Hooks

We use pre-commit hooks to ensure code quality and consistency. **This is required for all contributors.**
This mirrors the CI `code-quality` job. Code metrics run as part of pre-commit and
fail if any file is rated **bad** (see [Code Complexity Checks](#code-complexity-checks)).

### Install Pre-commit

```bash
# One time
python3.11 -m venv .venv

# Activate your virtual environment first
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate    # On Windows

# Install pre-commit package (if not already installed)
pip install pre-commit

# Install the git hook scripts
pre-commit install
```

### What Pre-commit Does

Our pre-commit configuration (`.pre-commit-config.yaml`) automatically:

- **Code Formatting**: Runs `black` to format Python code
- **Import Sorting**: Runs `isort` to organize imports
- **Linting**: Runs `flake8` for code quality checks
- **Type Checking**: Runs `mypy` for static type analysis
- **Python Security**: Runs `bandit` for security vulnerability scanning
- **Dockerfile Linting**: Runs `hadolint` to check Dockerfile best practices
- **Secrets Detection**: Runs `detect-secrets` and `gitleaks` to prevent credential leaks
- **Debug Guards**: Fails on `print`/`pdb` style debug statements
- **File Hygiene**: Trailing whitespace, end-of-file, mixed line endings
- **Config Validation**: Checks syntax for YAML/JSON/TOML files
- **Merge Conflict Detection**: Prevents committing unresolved conflicts
- **Large File Prevention**: Blocks files larger than 2 MB
- **Code Metrics Gate**: Fails if any file is **bad** for cyclomatic, cognitive, or MI

### Running Pre-commit Manually

```bash
# Run on all files
pre-commit run --all-files

# Run on staged files only
pre-commit run

# Update pre-commit hooks to latest versions
pre-commit autoupdate

# Skip pre-commit for emergency commits (not recommended - violates project rules)
# Note: User rules prohibit --no-verify flag
git commit -m "your message"  # Always runs pre-commit hooks
```

### Code Complexity Checks

Use the code metrics script to measure cyclomatic complexity, cognitive
complexity, and maintainability index for `pipeline`, `utils`, and `ui`:

```bash
# Activate virtual environment
source .venv/bin/activate

# Install metrics-only dependencies
pip install -r requirements.metrics.txt

# JS/TS cognitive complexity requires Node.js + frontend deps
cd ui/frontend && npm install && cd -

# Run the metrics script
python scripts/quality/code_metrics.py --fail-on-bad
```

If frontend dependencies are missing, you can skip JS/TS cognitive complexity:

```bash
python scripts/quality/code_metrics.py --skip-js-cognitive
```

Note: CI installs Node.js and frontend dependencies so JS/TS metrics run there.

## 🔒 Security

Security is a critical part of our development process. See [SECURITY.md](SECURITY.md) for full details.

### Security Scanning in Pre-commit

Pre-commit hooks run the following security checks on every commit:

- **Bandit**: Python static application security testing (SAST)
- **Hadolint**: Dockerfile security and best practice linting
- **detect-secrets**: Prevents accidental credential commits
- **Gitleaks**: Enhanced secret detection with regex patterns

### Security Scanning in CI

The GitHub Actions CI pipeline includes dedicated security jobs:

- **pip-audit**: Python dependency vulnerability scanning
- **npm audit**: JavaScript dependency vulnerability scanning
- **Bandit SAST**: Comprehensive Python security analysis with JSON reports
- **Hadolint**: Dockerfile linting for all Dockerfiles
- **Gitleaks**: Repository-wide secret scanning
- **Trivy**: Container image vulnerability scanning

### Frontend Security

The frontend uses ESLint security plugins:

- **eslint-plugin-security**: Detects potential security issues in JavaScript/TypeScript
- **eslint-plugin-sonarjs**: Code quality rules that catch security anti-patterns

### Dependency Management

Dependabot is configured to automatically create PRs for:

- Python dependency updates (pip)
- JavaScript dependency updates (npm)
- Docker base image updates
- GitHub Actions version updates

### Reporting Security Issues

If you discover a security vulnerability, please report it responsibly. See [SECURITY.md](SECURITY.md) for our security policy and reporting instructions.

## 🛠️ Making Changes

### Development Workflow

1. **Create a feature branch:**
   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Make your changes:**
   - Write code following our [Code Style](#code-style)
   - Add tests for new functionality
   - Update documentation as needed

3. **Test your changes:**
   - Run the Docker-based test commands in [Testing](#testing)

4. **Commit your changes** (see [Commit Guidelines](#commit-guidelines))

5. **Push and create PR:**
   ```bash
   git push origin feat/your-feature-name
   ```

### Types of Contributions

- **Bug Fixes**: Fix existing issues
- **Features**: Add new functionality
- **Documentation**: Improve docs, examples, or comments
- **Tests**: Add or improve test coverage
- **Performance**: Optimize existing code
- **Refactoring**: Improve code structure without changing functionality

## 📝 Commit Guidelines

We use [Conventional Commits](https://www.conventionalcommits.org/) format:

### Commit Format

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Commit Types

- **feat:** New features
- **fix:** Bug fixes
- **docs:** Documentation changes
- **style:** Code style changes (formatting, etc.)
- **refactor:** Code refactoring
- **test:** Adding or modifying tests
- **chore:** Build process or auxiliary tool changes
- **perf:** Performance improvements
- **ci:** CI/CD pipeline changes
- **build:** Build system or dependencies

### Examples

```bash
feat: add language detection to parse pipeline
fix: resolve PDF parsing error for large documents
docs: update README with metadata preparation examples
test: add unit tests for summarization module
chore: update dependencies to latest versions
```

### Commit Best Practices

- Keep commits atomic (one logical change per commit)
- Write clear, descriptive commit messages
- Reference issues when applicable: `fixes #123`
- Use imperative mood: "add feature" not "added feature"

## 🧪 Testing

### Run Tests (Docker)

```bash
# Start services (required for integration and UI tests)
docker compose up -d

# Run unit tests (fast)
docker compose exec pipeline pytest tests/unit/ -v

# Run frontend unit tests (React)
docker compose exec -e CI=true ui npm test -- --watchAll=false

# Run integration tests (requires API + UI containers)
API_BASE_URL=http://api:8000 UI_BASE_URL=http://ui:3000 \
  docker compose exec pipeline pytest tests/integration/ -v -s

# Run all tests (pipeline container)
docker compose exec pipeline pytest -v
```

For additional test details, see `tests/README.md`.

### Manual Verification (UI)

When changes affect parsing, chunking, or rendering, validate in the UI:

1. Re-index a document and open it in the UI.
2. Search for a query that returns figures/tables.
3. Confirm images, tables, and inline references render in the right order.

## 🔎 Evaluation

Evaluation scripts call live LLMs and the running API. Expect latency and
token costs.

### Search Evaluation

```bash
# Generate a small synthetic dataset
docker compose exec pipeline \
  python tests/evaluation/search/generate_search_tests.py --num-queries 5

# Run evaluation (default model from env)
docker compose exec pipeline python tests/evaluation/search/evaluate.py

# Specify embedding model and rerank
docker compose exec pipeline \
  python tests/evaluation/search/evaluate.py --model e5_large --rerank
```

### TOC Classification Evaluation

```bash
# LLM-judge TOC hierarchy for multiple documents
docker compose exec pipeline \
  python tests/evaluation/toc_classification/test_toc_hierarchy.py --records 5

# Evaluate a specific document (optionally reparse)
docker compose exec pipeline \
  python tests/evaluation/toc_classification/predict_one_toc_all.py --file-id <file_id> --data-source uneg

# Bulk tag prediction from a CSV file
docker compose exec pipeline \
  python tests/evaluation/toc_classification/predict_toc_tags.py <input_csv> <output_csv>
```

## ⚡ Performance Tests

Performance scripts live in `scripts/performance/` and expect the Docker stack
to be running.

```bash
# Quick API latency check across model combos
docker compose exec pipeline \
  python scripts/performance/verify_search_performance.py

# Stress test /search with concurrency
docker compose exec pipeline \
  python scripts/performance/search-stress-test.py \
    --data-source uneg --base-url http://api:8000 --run-both

# Qdrant hybrid query diagnostics
docker compose exec -e QDRANT_HOST=http://qdrant:6333 pipeline \
  python scripts/performance/verify_qdrant_performance.py
```

## ✅ GitHub Actions (CI)

The CI workflow in `.github/workflows/ci.yml` runs on push and PRs:

- **code-quality**: Pre-commit hooks (formatting, linting, type checks, security scans).
- **security-scan**: Dependency audits (pip-audit, npm audit), Bandit SAST, Hadolint, Gitleaks.
- **container-scan**: Trivy vulnerability scanning on Docker images.
- **tests**: Python unit tests (`pytest tests/unit/`).
- **integration-tests**: Docker Compose stack + integration tests.
- **ui-tests**: React unit tests (`npm test -- --watchAll=false`).

Secrets and environment variables for integrations are configured in GitHub
Actions (`HUGGINGFACE_API_KEY`, API URLs, etc.).

### Dependabot

Dependabot is configured (`.github/dependabot.yml`) to automatically create weekly PRs for:

- Python dependencies (`requirements.txt`)
- NPM dependencies (`ui/frontend/package.json`)
- Docker base images
- GitHub Actions versions

## 🔍 Pull Request Process

### Before Submitting

1. **Update your branch:**
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Run all checks:**
   - Run the Docker-based test commands in [Testing](#testing)

3. **Update documentation** if needed

### PR Guidelines

- **Title**: Use conventional commit format
- **Description**: Clearly explain what and why
- **Link Issues**: Reference related issues
- **Screenshots**: Include for UI changes
- **Breaking Changes**: Clearly document any breaking changes

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Other: ___

## Testing
- [ ] Tests pass locally
- [ ] New tests added for new functionality
- [ ] Manual testing completed

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review of code completed
- [ ] Documentation updated
- [ ] No breaking changes (or clearly documented)
```

### Review Process

1. **Automated Checks**: CI/CD pipeline runs tests and linting
2. **Peer Review**: At least one maintainer reviews the code
3. **Feedback**: Address any requested changes
4. **Approval**: Maintainer approves and merges

## 🐛 Issue Guidelines

### Before Creating an Issue

1. **Search existing issues** to avoid duplicates
2. **Check documentation** for common solutions
3. **Test with latest version**

### Bug Reports

Include:
- **Environment**: OS, Python version, package versions
- **Steps to reproduce** the issue
- **Expected behavior**
- **Actual behavior**
- **Error messages** (full stack trace)
- **Minimal code example**
- **Sample metadata file** (if related to parsing/summarization)

### Feature Requests

Include:
- **Clear description** of the feature
- **Use case** and motivation
- **Proposed solution** (if you have one)
- **Alternatives considered**

## 🎨 Code Style

### Python Style Guide

- **Formatter**: Black (line length: 88 characters)
- **Import Sorting**: isort (Black-compatible profile)
- **Linting**: flake8 with extensions for complexity and security
- **Type Checking**: mypy (strict mode)
- **Type Hints**: Use type hints for function signatures
- **Docstrings**: Google style docstrings

### Code Quality Requirements

1. **Type Hints**: All functions must have type hints
2. **Docstrings**: All public functions and classes must have docstrings
3. **Test Coverage**: Minimum 90% test coverage for new code
4. **Security**: No security vulnerabilities (checked by Bandit)
5. **Complexity**: Keep cyclomatic complexity under 10

### Code Quality Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Format code
black pipeline/ tests/
isort pipeline/ tests/

# Check code quality
flake8 pipeline/ tests/
mypy pipeline/
```

## 🚀 Adding New Features

### Process

1. **New Pipeline Scripts**: Add new pipeline components in the `pipeline/` directory
2. **Include proper type hints and documentation** for all functions
3. **Add corresponding tests** in `tests/`
4. **Update the README** with documentation for your feature
5. **Update metadata columns** if your feature adds new data to the Excel file

### Extending the Pipeline

New pipeline stages should:
- Read from and write to the metadata Excel file
- Follow the existing pattern of parse → summarize → stats
- Include error handling and logging
- Support command-line arguments for flexibility

## 🔄 Release Process

For maintainers:

1. **Version Bump**: Update version in `pyproject.toml`
2. **Changelog**: Update release notes
3. **Tag Release**: Create git tag
4. **GitHub Release**: Create release with notes
5. **PyPI**: Automated via GitHub Actions

## 📞 Getting Help

- **Documentation**: Check the README and code comments
- **Issues**: Create a GitHub issue for bugs or feature requests
- **Discussions**: Use GitHub Discussions for questions
- **UNEG Resources**: Consult [UNEG Evaluation Reports](https://www.unevaluation.org/)

## 🙏 Recognition

Contributors will be recognized in:
- GitHub contributors list
- Release notes for significant contributions
- Project acknowledgments

Thank you for contributing to the Humanitarian Evaluation AI Research Pipeline! 🎉
