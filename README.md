# Evidence Lab

[![CI](https://github.com/dividor/evidencelab/actions/workflows/ci.yml/badge.svg)](https://github.com/dividor/evidencelab/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Introduction

![Evidence Lab](ui/frontend/public/docs/images/evidence-lab.png)

Evidence Lab is a free open source platform that provides a document pipeline, search, and AI-powered information discovery tools. The aim is to provide a quick start for those looking to use AI with their documents and a place where new ideas can be tested.

You can run the code yourself, or explore the online version at [evidencelab.ai](https://evidencelab.ai) which has so far been populated with about 20,000 United Nations humanitarian evaluation reports sourced from the [United Nations Evaluation Group](https://www.un.org/evaluations). See [Data](ui/frontend/public/docs/data.md) for more information on these amazing documents.

If you would like to have your public documents added to Evidence Lab, or would like to contribute to the project, please reach out to [evidencelab@astrobagel.com](mailto:evidencelab@astrobagel.com).

Also, for the latest news check out the [AstroBagel Blog](https://medium.com/@astrobagel).

## Philosophy

Evidence Lab grew out of research work for the [AstroBagel Blog](https://medium.com/@astrobagel). The core design principles are:

* **Runs on a desktop** — the full pipeline can process 20,000 30-page documents in a week for less than $50
* **Configurable** — point it at a folder of PDFs and configure via a single `config.json`
* **Progressive complexity** — start with simple parsing and layer on richer features (image annotation, reranking) later without re-processing
* **Model-agnostic** — supports both open-source and proprietary embedding and LLM models
* **Observable** — built-in tools for monitoring pipeline progress and exploring AI retrieval quality

Some lofty, often conflicting, goals! Always a work in progress, and low-cost high-speed processing which runs on a desktop computer, does come with a few shortcuts. To run on a modest server, the user interface might not be the fastest out there (but can be if you add more processing power), and in not using expensive LLMs for parsing (only cheap ones!), the ingestion had to be tuned to the document data styles. That said, the design has tried to allow for future improvements.

## Features

Evidence Lab document processing pipeline includes the following features:

1. Processing pipeline

- PDF/Word parsing with Docling, to include document structure detection
- Footnote and references, images and table detection
- Basic table extraction, with support for more expensive processing as required
- AI-assisted document summarization
- AI-assisted tagging of documents
- Indexing with Open (Huggingface) or proprietary models (Azure foundry, but extensible)

2. User interface

| Search | Heatmapper | Pipeline |
|:---:|:---:|:---:|
| <img src="ui/frontend/public/docs/images/search.png" alt="Search" height="200"> | <img src="ui/frontend/public/docs/images/heatmapper.png" alt="Heatmapper" height="200"> | <img src="ui/frontend/public/docs/images/pipeline.png" alt="Pipeline" height="200"> |

- Hybrid search with AI summary and reranking
- Field boosting — detects countries/organizations in the query and promotes matching results; at full weight, non-matching results are excluded
- Experimental features such as heatmapper for tracking trends in content
- Filtering by metadata, in-document section types
- Search and reranking settings to explore different models
- Auto min score filtering using percentile-based thresholding (filters bottom 30% of results)
- Semantic highlighting in search results
- Basic language translation
- PDF preview with in-document search
- Administration views to track pipeline, documents, performance and errors

3. User authentication & permissions (opt-in)

- Email/password registration with email verification, or OAuth single sign-on (Google, Microsoft)
- Cookie-based sessions with CSRF protection — no tokens in localStorage
- Account lockout, rate limiting, and audit logging for security
- Group-based data-source access control — restrict which datasets users can see
- Admin panel for managing users, groups, and permissions
- Self-service profile management and account deletion
- Built on [fastapi-users](https://fastapi-users.github.io/fastapi-users/) with future MFA support in mind
- Enabled via `USER_MODULE=true` in `.env` (disabled by default)

More features will be added soon, focused on document evidence analysis.

## Getting started

You can explore the hosted version at [evidencelab.ai](https://evidencelab.ai).

### Quick Start

1. **Configure data sources**
   - Edit [`config.json`](config.json) in the repo root to define `datasources`, `data_subdir`, `field_mapping`, and `taxonomies`.
   - The UI reads the same `config.json` via Docker Compose.

2. **Set environment variables**
   - Copy [`.env.example`](.env.example) to `.env`.
   - Fill in the API keys and service URLs required by the pipeline and UI.

3. **Add documents + metadata**
   - Save documents under `data/<data_subdir>/pdfs/<organization>/<year>/`.
   - For each document, include a JSON metadata file with the same base name.
   - If a download failed, add a `.error` file with the same base name (scanner records these).

   Example layout:
   ```
   data/
     uneg/
       pdfs/
         UNDP/
           2024/
             report_123.pdf
             report_123.json
             report_124.error (if there was an error downloading the file)
   ```

4. **Run the pipeline (Docker)**
   ```bash
   # Start services
   docker compose up -d --build

   # Run the orchestrator (example: UNEG)
   docker compose exec pipeline \
     python -m pipeline.orchestrator --data-source uneg --skip-download --num-records 10
   ```

   > **Tip:** To quickly ingest a single test document and verify the full stack,
   > run the integration test script instead:
   > ```bash
   > ./tests/integration/run_integration_host_pipeline.sh
   > ```
   > This ingests a sample report, rebuilds the containers, and runs the
   > integration test suite end-to-end.

5. **Access the Evidence Lab UI**
   - Open http://localhost:3000
   - Select your data source and search the indexed documents

6. **Next steps**
   - To add user authentication see [User authentication](#user-authentication) below
   - See the technical deep dive for pipeline commands, downloaders, and architecture details:
     [`ui/frontend/public/docs/tech.md`](ui/frontend/public/docs/tech.md)
   - See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup, pre-commit hooks,
     testing, and contribution guidelines

## User authentication

User authentication is **opt-in** and disabled by default. When enabled it adds email/password registration, OAuth single sign-on, group-based data-source access control, and an admin panel.

### 1. Enable the module

Set these in your `.env`:

```env
USER_MODULE=true
REACT_APP_USER_MODULE=true
AUTH_SECRET_KEY=<generate-a-random-secret-at-least-32-characters>
```

> **Tip:** Generate a secret with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

### 2. Configure email (SMTP)

Email is used for account verification and password resets. For **production**, configure a real SMTP provider (SendGrid, AWS SES, Gmail, etc.):

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=noreply@yourdomain.com
SMTP_USE_TLS=true
```

For **local development**, use [Mailpit](https://mailpit.axllent.org/) — a lightweight SMTP server that catches all outgoing emails:

```bash
# Start Mailpit alongside the other services
docker compose --profile mail up -d mailpit

# Open the Mailpit web UI to view caught emails
open http://localhost:8025
```

Then set these values in your `.env`:

```env
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USE_TLS=false
```

Restart the API container to pick up the new settings:

```bash
docker compose up -d api
```

All verification and password-reset emails will now appear in the Mailpit inbox at http://localhost:8025.

### 3. Configure OAuth (optional)

To enable Google and/or Microsoft single sign-on, add the relevant credentials to `.env`:

```env
# Google OAuth
OAUTH_GOOGLE_CLIENT_ID=your-client-id
OAUTH_GOOGLE_CLIENT_SECRET=your-client-secret

# Microsoft OAuth
OAUTH_MICROSOFT_CLIENT_ID=your-client-id
OAUTH_MICROSOFT_CLIENT_SECRET=your-client-secret
OAUTH_MICROSOFT_TENANT_ID=common
```

Leave these blank to disable OAuth and use email/password registration only.

### 4. Create the first admin user

There is no default admin account. To bootstrap the first administrator:

1. Add the admin email to `.env`:

   ```env
   FIRST_SUPERUSER_EMAIL=you@example.com
   ```

2. Register that account through the UI (or via OAuth) and verify the email
3. Restart the API — the user is automatically promoted to superuser on startup

Once you have an admin account, you can promote other users from the **Admin → Users** tab in the UI.

### 5. Configure groups and data-source access

Evidence Lab uses groups to control which data sources users can see:

- A **Default** group is created automatically and grants access to **all** data sources. New users are added to this group on registration.
- To **restrict access**, create additional groups from the **Admin → Groups** panel, assign specific data-source keys to each group, and move users into the appropriate groups.
- Users who are only in non-default groups will see only the data sources assigned to their groups.

### Additional settings

See [`.env.example`](.env.example) for the full list of auth-related settings including:

| Setting | Default | Description |
|---------|---------|-------------|
| `FIRST_SUPERUSER_EMAIL` | *(empty)* | Email of the account to auto-promote to admin on startup |
| `AUTH_ALLOWED_EMAIL_DOMAINS` | *(empty — open)* | Comma-separated whitelist of allowed email domains |
| `AUTH_MIN_PASSWORD_LENGTH` | `8` | Minimum password length |
| `AUTH_COOKIE_SECURE` | `true` | Set to `false` for non-HTTPS local dev |
| `AUTH_RATE_LIMIT_MAX` | `10` | Max login attempts per IP per window |
| `AUTH_RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds |
| `AUTH_LOCKOUT_THRESHOLD` | `5` | Failed logins before account lockout |
| `AUTH_LOCKOUT_DURATION_MINUTES` | `15` | Lockout duration |
