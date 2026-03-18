# Evidence Lab

[![CI](https://github.com/dividor/evidencelab/actions/workflows/ci.yml/badge.svg)](https://github.com/dividor/evidencelab/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Introduction

![Evidence Lab](docs/images/evidence-lab.png)

Evidence Lab is a free open source platform that provides a document pipeline, search, and AI-powered information discovery tools. The aim is to provide a quick start for those looking to use AI with their documents and a place where new ideas can be tested.

You can run the code yourself, or explore the online version at [evidencelab.ai](https://evidencelab.ai) which has so far been populated with about 20,000 United Nations humanitarian evaluation reports sourced from the [United Nations Evaluation Group](https://www.un.org/evaluations). See [Data](ui/frontend/public/docs/data.md) for more information on these amazing documents.

If you would like to have your public documents added to Evidence Lab, or would like to contribute to the project, please reach out to [evidencelab@astrobagel.com](mailto:evidencelab@astrobagel.com).

Also, for the latest news check out the [AstroBagel Blog](https://medium.com/@astrobagel).

## Philosophy

Evidence Lab grew out of research work for the [AstroBagel Blog](https://medium.com/@astrobagel). The core design principles are:

* **Runs on a desktop** — the full pipeline can process 20,000 30-page documents in a week on an Apple M4 Pro mini, for less than $50
* **Configurable** — point it at a folder of PDFs and configure via a single `config.json`
* **Progressive complexity** — start with simple parsing and layer on richer features (image annotation, reranking) later without re-processing
* **Model-agnostic** — supports both open-source and proprietary embedding and LLM models
* **Observable** — built-in tools for monitoring pipeline progress and exploring AI retrieval quality

Some lofty, often conflicting, goals! Always a work in progress, and low-cost high-speed processing which runs on a desktop computer, does come with a few shortcuts. To run on a modest server, the user interface might not be the fastest out there (but can be if you add more processing power), and in not using expensive LLMs for parsing (only cheap ones!), the ingestion had to be tuned to the document data styles. That said, the design has tried to allow for future improvements.

## Features

<a href="https://www.loom.com/share/b3043d80834e44b3b935b7db7a086a1d"><img src="https://cdn.loom.com/sessions/thumbnails/b3043d80834e44b3b935b7db7a086a1d-04eb569ecf17a386.jpg" alt="Overview video" width="300"></a>

**[Overview video](https://www.loom.com/share/b3043d80834e44b3b935b7db7a086a1d)**

Evidence Lab document processing pipeline includes the following features:

1. Processing pipeline

- PDF/Word parsing with Docling, to include document structure detection
- Footnote and references, images and table detection
- Basic table extraction, with support for more expensive processing as required
- AI-assisted document summarization
- AI-assisted tagging of documents
- Indexing with Open (Huggingface) or proprietary models (Azure foundry, but extensible)

2. User interface

| Search | Research Assistant | Heatmapper | Pipeline |
|:---:|:---:|:---:|:---:|
| <img src="docs/images/search-guide/search-results-full.png" alt="Search" height="200"> | <img src="docs/images/assistant/assistant-response.png" alt="Research Assistant" height="200"> | <img src="docs/images/heatmapper-overview.png" alt="Heatmapper" height="200"> | <img src="docs/images/monitor/pipeline-view.png" alt="Pipeline" height="200"> |

- Hybrid search with AI summary and reranking
- **Research Assistant** — chat-based AI agent that searches, analyzes, and synthesizes findings with inline citations and multi-turn conversations with thread history
- **Deep Research mode** — coordinator/researcher sub-agent architecture using [deepagents](https://github.com/krrome/deepagents) for thorough multi-step investigations with real-time streaming progress
- **Star ratings** — rate search results, AI summaries, and assistant responses with 1–5 stars and optional comments
- **Drilldown research** — highlight text or click "Find out more" to drill into sub-topics, building an explorable research tree with query inheritance and PDF export
- Field boosting — detects countries/organizations in the query and promotes matching results; at full weight, non-matching results are excluded
- Experimental features such as heatmapper for tracking trends in content
- Config-driven filter fields — control which metadata fields appear in the filter panel
- Filtering by metadata, in-document section types
- Search and reranking settings to explore different models
- Auto min score filtering using percentile-based thresholding (filters bottom 30% of results)
- Semantic highlighting in search results
- Basic language translation
- PDF preview with in-document search
- Built-in searchable documentation area with sidebar navigation
- Administration views to track pipeline, documents, performance and errors

3. User authentication & permissions (opt-in)

- Email/password registration with email verification, or OAuth single sign-on (Google, Microsoft)
- Cookie-based sessions with CSRF protection — no tokens in localStorage
- Account lockout, rate limiting, and audit logging for security
- Group-based data-source access control — restrict which datasets users can see
- Admin panel for managing users, groups, and permissions
- User feedback — rate search results, AI summaries, documents, and taxonomy with 1–5 stars
- Activity logging — automatic search activity capture with admin views and XLSX export
- Self-service profile management and account deletion
- Built on [fastapi-users](https://fastapi-users.github.io/fastapi-users/) with future MFA support in mind
- Three modes via `USER_MODULE` in `.env`: `off` (default), `on_passive` (optional login), `on_active` (login required)

More features will be added soon, focused on document evidence analysis and MCP (Model Context Protocol) support. See the [CHANGELOG](CHANGELOG.md) for the full list of recent additions.

## Getting started

You can explore the hosted version at [evidencelab.ai](https://evidencelab.ai).

### Demo (quickest way to try it)

The interactive demo script guides you through provider selection, API key
setup, downloads a few World Bank documents, and runs the full pipeline.

**Running on host** (recommended — can use hardware acceleration such as Apple
MPS or NVIDIA CUDA, but may require some adjustments to suit your environment):

```bash
# Create and activate a virtual environment
python3 -m venv ~/.venvs/evidencelab-ai
source ~/.venvs/evidencelab-ai/bin/activate
pip install -r requirements.txt

# Start infrastructure services (Qdrant, PostgreSQL)
docker compose up -d qdrant postgres

# Run the demo — interactive setup will prompt for provider and API keys
python scripts/demo/run_demo.py --mode host
```

The script will automatically configure `.env`, add a demo datasource to
`config.json`, download documents, and run the pipeline.

**Running in Docker** (guaranteed to work on any Docker-capable machine, but
can be significantly slower as it cannot utilise GPU or Apple MPS acceleration
on your host):

```bash
# Start all services
docker compose up -d --build

# Run the demo
python scripts/demo/run_demo.py --mode docker
```

Once complete, open http://localhost:3000 and select the **demo** data source.

**Options:**

```bash
python scripts/demo/run_demo.py --mode host --num-docs 10   # Download more documents
python scripts/demo/run_demo.py --mode host --skip-download  # Re-run pipeline only
python scripts/demo/run_demo.py --mode host --skip-pipeline  # Download only
```

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

## Configuration Reference

All configuration lives in a single [`config.json`](config.json) at the repo root. The file is shared between the pipeline and the UI via Docker Compose volumes.

### `application`

Global application settings.

| Key | Type | Description |
|-----|------|-------------|
| `ai_summary.enabled` | `bool` | Enable AI-generated summaries in search results |
| `features.semantic_highlights` | `bool` | Enable semantic highlighting of relevant passages |
| `features.pdf_highlights` | `bool` | Enable highlighting within the PDF preview |
| `search.dense_weight` | `float` | Default weight for the dense (semantic) component in hybrid search (0–1) |
| `search.short_query_dense_weight` | `float` | Dense weight override for short queries |
| `search.highlight_threshold` | `float` | Minimum score for semantic highlights |
| `search.page_size` | `int` | Default number of search results per page |
| `search.rerank_model` | `string` | Default reranker model ID (must exist in `supported_rerank_models`) |
| `search.default_dense_model` | `string` | Default dense embedding model key (must exist in `supported_embedding_models`) |

### `assistant`

Research Assistant configuration.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | `bool` | `true` | Enable the Research Assistant tab |
| `max_search_results` | `int` | `20` | Maximum search results per tool call |
| `max_iterations` | `int` | `3` | Maximum agent iterations |
| `max_queries` | `int` | `4` | Maximum search queries per session |
| `recursion_limit` | `int` | `12` | LangGraph recursion limit |
| `deep_research.max_queries` | `int` | `10` | Maximum queries for deep research |
| `deep_research.recursion_limit` | `int` | `100` | Recursion limit for deep research |

### `supported_embedding_models`

A dictionary of embedding models available to the pipeline and search engine.

```jsonc
"model_key": {
  "model_id": "namespace/model-name",   // Model identifier (HuggingFace repo, Azure deployment, etc.)
  "size": 1024,                          // Embedding vector dimensionality
  "source": "huggingface",              // Provider: "huggingface", "azure_foundry", "google_vertex", "qdrant", "opensearch"
  "type": "dense"                        // "dense" or "sparse"
}
```

### `supported_llms`

A dictionary of LLM configurations used for summarization and tagging.

```jsonc
"llm_key": {
  "model": "namespace/model-name",       // Model identifier
  "provider": "huggingface",            // Provider: "huggingface", "azure_foundry"
  "inference_provider": "together"      // Optional: specific inference endpoint
}
```

### `supported_rerank_models`

A dictionary of reranker models available for result reranking.

```jsonc
"model_key": {
  "model_id": "namespace/model-name",
  "provider": "azure_foundry",          // or "source": "huggingface"
}
```

### `ui_model_combos`

Named model combinations selectable in the UI search settings. Each combo bundles an embedding model, sparse model, summarization model, highlighting model, and reranker.

```jsonc
"Combo Name": {
  "embedding_model": "model_key",       // Key from supported_embedding_models
  "sparse_model": "model_key",          // Key from supported_embedding_models (type: sparse)
  "summarization_model": {              // Inline LLM config for AI summaries
    "model": "model-name",
    "max_tokens": 2000,
    "temperature": 0.2,
    "chunk_overlap": 800,
    "chunk_tokens_ratio": 0.5
  },
  "semantic_highlighting_model": { ... },  // Inline LLM config for highlights
  "reranker_model": "model_key",        // Key from supported_rerank_models
  "rerank_model_page_size": 10          // Optional: candidates per rerank batch
}
```

### `datasources`

Per-datasource configuration. Each key is the datasource display name, and the value configures everything from field mapping to pipeline processing.

#### `data_subdir`

Directory name under `data/` for this datasource's files (e.g. `"uneg"` maps to `data/uneg/`).

#### `field_mapping`

Maps logical field names used by the application to actual field names in the source metadata. The mapping controls how metadata JSON fields are stored in PostgreSQL and Qdrant.

```jsonc
"field_mapping": {
  "organization": "agency",           // Core field → source metadata field
  "language": "sys_language",         // sys_ prefix: system-generated field
  "region": "region",                 // Additional metadata field
  "pdf_url": "pdf_url"               // URL fields for document access
}
```

**Field name prefixes** (used across the system, not just in `field_mapping`):

| Prefix | Meaning | Storage | Example |
|--------|---------|---------|---------|
| *(none)* | Core mapped field — stored with a `map_` prefix in Qdrant | Qdrant `map_*` payload, PostgreSQL | `"organization": "agency"` |
| `src_` | Raw source metadata — passed through to Qdrant as-is | Qdrant payload (verbatim) | `src_geographic_scope` |
| `sys_` | System-generated field (e.g. detected language) | Qdrant `sys_*` payload, PostgreSQL | `"language": "sys_language"` |
| `tag_` | AI-generated taxonomy tag — stored per chunk | Qdrant chunks collection | `tag_sdg`, `tag_cross_cutting_theme` |

#### `filter_fields`

Defines which fields appear in the UI filter panel and their display labels. The **key order controls UI display order**. This is the single source of truth for the filter panel.

```jsonc
"filter_fields": {
  "organization": "Organization",                    // Core mapped field
  "title": "Document Title",
  "published_year": "Year Published",
  "document_type": "Document Type",
  "country": "Country",
  "src_geographic_scope": "Geographic Scope",        // Source metadata field
  "tag_sdg": "United Nations Sustainable Development Goals",  // AI taxonomy tag
  "tag_cross_cutting_theme": "Cross-cutting Themes", // AI taxonomy tag
  "language": "Language"
}
```

All three field types work as filter fields:
- **Core fields** (e.g. `organization`) — facet values are read from PostgreSQL via the field mapping
- **`src_*` fields** (e.g. `src_geographic_scope`) — facet values are read from Qdrant document payloads
- **`tag_*` fields** (e.g. `tag_sdg`) — facet values are read from Qdrant chunks collection; taxonomy keys under `pipeline.tag.taxonomies` become `tag_<key>` fields

#### `pipeline`

Pipeline processing configuration with the following sub-sections:

| Sub-section | Description |
|-------------|-------------|
| `processing_timeout` | Maximum seconds for a single document to be processed |
| `download` | Download command and arguments (supports `{data_dir}`, `{num_records}`, `{year}`, etc. placeholders) |
| `parse` | PDF/Word parsing settings (`use_subprocess`, `table_mode`, `no_ocr`, `images_scale`, `enable_superscripts`) |
| `chunk` | Text chunking settings (`max_tokens`, `min_substantive_size`, `dense_model` for token counting) |
| `summarize` | AI summarization settings (`enabled`, `llm_model`, `llm_workers`, `context_window`) |
| `tag` | AI tagging settings (`enabled`, `dense_model`, `llm_model`, `taxonomies`) |
| `index` | Indexing settings (`batch_size`, `embedding_workers`, `dense_models`, `sparse_models`) |

#### `pipeline.tag.taxonomies`

Defines taxonomy classifications applied to documents by the AI tagger. Each taxonomy key (e.g. `sdg`) becomes a `tag_<key>` field in Qdrant chunk payloads.

```jsonc
"taxonomies": {
  "sdg": {                                // Becomes tag_sdg in Qdrant
    "name": "United Nations Sustainable Development Goals",
    "level": "document",                  // "document" or "chunk"
    "input": "summary",                   // Input text: "summary" or "content"
    "type": "multi",                      // "multi" (multiple tags) or "single"
    "values": {
      "sdg1": {
        "name": "SDG1 - No Poverty",
        "definition": "...",              // Human-readable definition
        "llm_prompt": "..."              // Prompt used by the LLM tagger
      }
    }
  }
}
```

To make a taxonomy filterable in the UI, add `tag_<key>` to `filter_fields` (see above).

## User authentication

User authentication is **opt-in** and disabled by default. When enabled it adds email/password registration, OAuth single sign-on, group-based data-source access control, and an admin panel.

### 1. Enable the module

`USER_MODULE` supports three modes:

| Mode | Description |
|------|-------------|
| `off` | No authentication (default) |
| `on_passive` | Auth UI available but optional — anonymous users can browse freely, registered users get profiles and permissions |
| `on_active` | All access requires login — unauthenticated users cannot see datasources |

Set these in your `.env`:

```env
USER_MODULE=on_active
REACT_APP_USER_MODULE=on_active
AUTH_SECRET_KEY=<generate-a-random-secret-at-least-32-characters>
```

> Legacy values `true`/`false` are still supported (`true` → `on_active`, `false` → `off`).

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
