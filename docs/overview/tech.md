## Document Processing Pipeline

![Pipeline Architecture](/docs/images/admin/architecture/pipeline-architecture.png)

The pipeline is modular and managed by `orchestrator.py`. If you put PDF/DOCX files in some folders, each with a metadata JSON file for extra information, orchestrator will do everything else.

**Note**: Individual processing modules for downloading content are external to this repository to separate sourcing from processing logic.

### 1. Parser (`parser.py`)

The parser has been designed to be inexpensive and relatively fast, while saving assets such as images and tables which can be reprocessed later with more advanced/expensive techniques as required.

Uses [Docling](https://github.com/DS4SD/docling) for advanced document understanding, leveraging its [hierarchical structure capabilities](https://ds4sd.github.io/docling/concepts/chunking/).

* **Hierarchical Parsing**: Extracts the full document structure (headers, sections, paragraphs) rather than just flat text.
* **Rich Content Capture**:
  * **Images & Tables**: Identifies and extracts images of Figures and Tables, saving them as distinct assets.
  * **Markdown Generation**: Converts the document into a structured Markdown representation where images and tables are referenced by their path.
* **Post-Processing**:
  * **Hierarchy Inference**: Uses the [docling-hierarchical-pdf](https://github.com/krrome/docling-hierarchical-pdf) post-processor to reconstruct proper heading hierarchy (e.g., ensuring "1.1" is nested under "1.0") using font size and numbering heuristics.
  * **PyMuPDF TOC Fallback**: If Docling's TOC looks low quality or empty, the parser falls back to the PDF outline (bookmarks) via PyMuPDF.
  * **Superscript Identification**: Uses geometric analysis to identify unlinked superscripts (footnotes).
  * **Caption Classification**: Reclassifies headers that are actually captions to associate them correctly with images.
  * **Encoding Cleanup**: Fixes common encoding artifacts (e.g., ligatures, Unicode replacement characters).

### 2. Chunking & Enrichment (`chunker.py`)

Transforms raw parsed text into excerpts/chunks.

* **Hierarchical Chunking**: Respects semantic boundaries (paragraphs, headers) while adhering to token limits. Merges small "orphaned" text blocks with their robust neighbors.
* **Footnote Integration**:
  * **Detection**: Identifies inline citation markers (e.g., `^12`, `[12]`).
  * **Resolution**: Scans the entire document for the corresponding footnote definition and dynamically appends the footnote text to the chunk where it is cited. This ensures that chunks containing "See Reference 12" also contain the actual text of Reference 12 for searchability.
* **Visual Enrichment**:
  * **Image Association**: Uses bounding box geometry to spatially associate extracted images with the text chunks that physically surround or reference them (e.g., a chunk containing "Figure 1" gets the actual image of Figure 1 attached).
  * **Captions**: Ensures captions are bundled with their respective images and chunks.
* **Text Reconstruction**: Rebuilds the searchable text for each chunk by combining paragraph text and structured table content, ensuring tables are searchable.

### 3. Summarization (`summarizer.py`)

Generates comprehensive document summaries using a multi-strategy approach:

* **Methodology**:

See [here](https://medium.com/data-science-collective/a-low-cost-pipeline-for-generating-abstracts-of-humanitarian-evaluation-reports-4efe231cd4ea) for discussion on the summarization technique.

LLM Summarization is done using a Map-Reduce process, splitting text into chunks and summarizing in parallel. The summaries are then reduced into a single summary using the LLM.

The chunks are determined by using the document structure and matching for sections with titles similar to 'Executive summary', 'Abstract', etc. If this isn't possible, the document is split into chunks and clustered according to semantic similarity. The clusters centroid is used to find representative chunks, which are then summarized.

### 4. Tagger (`tagger.py`)

Classifies every chunk into a taxonomy (`findings`, `methodology`, `executive_summary`, etc.). This is done using a hybrid approach that combines deterministic keyword rules with LLM-based classification for ambiguous headers, coupled with TOC propagation.

It should be noted this LLM/Heuristics approach is imperfect and meant as a way to seed the system. The user interface also supports being able to correct and approve section categories, to be used to train more accurate classification models in later phases.

**Taxonomy Classification**:
The system also supports configurable document-level taxonomies (defined in `config.json`). For example, classifying documents against **Sustainable Development Goals (SDGs)**. This is performed by analyzing the comprehensive document summary with an LLM and storing the results as faceted tags in the search index.

### 5. Indexer (`indexer.py`)

Prepares and stores content in **Qdrant** with placeholders for a range of vector embedding models.

* **Multi-Vector Indexing**: Stores multiple vectors per chunk to support different retrieval strategies.
  * **Dense**: Semantic vectors (defaulting to `multilingual-e5-large`, with support for Azure Foundry `text-embedding-3` models).
  * **Sparse**: BM25 keyword vectors for exact term matching.
* **Model Agnostic**: Designed to swap embedding backends (Azure Foundry, Huggingface) via configuration.
* **Document Embeddings**: Generates a separate "Document Level" embedding (Title + Summary) to support "More like this" recommendations at the document level.

## Search & Discovery

![Application Architecture](/docs/images/admin/architecture/app-architecture.png)

Search powered by hybrid retrieval and AI.

* **Hybrid Search (RRF)**: Uses Reciprocal Rank Fusion to mathematically combine results from Semantic Search (Dense) and Keyword Search (Sparse). This captures both "conceptual matches" and "exact phrase matches".
* **Intelligent Reranking**: Optionally applies a reranking step to re-score the top results, significantly improving precision. Supports Cohere Rerank (via Azure Foundry) and Jina Reranker (via Huggingface).
* **Recency Boosting**: Applies a Gaussian decay function to boost newer documents while retaining relevance for older, highly distinct matches.
* **Field Boosting**: Configurable per data source, detects field values (e.g., country names, organizations) mentioned in the query and boosts matching results. At weight < 1.0, uses a multiplicative bonus (`score * (1 + weight)`) so non-matching results are never penalized. At weight = 1.0, acts as a hard filter — results whose metadata field does not match the detected value are excluded entirely.
* **Faceted Navigation**: Filter by Organization, Year, Language, and Format.
* **Cross-Lingual features**:
  * **Translation**: Translate search results (titles + snippets) into 10+ languages on request.
  * **Semantic Highlighting**: Highlights relevant phrases in the result snippet effectively, even when the search terms are in a different language from the result.
* **AI Search Summary**: Generates a direct answer to the user's query by synthesizing the top search results.
* **Drilldown Research**: Highlight text in an AI summary or click "Find out more" on the top heading to automatically drill into sub-topics. Each sub-query inherits the root search query plus the immediate parent topic for context, building an explorable tree of research. The tree view lets you navigate back to any previous node to review its results and summary. Sub-queries also inherit all active filters (data source, date range, etc.) from the parent search.
* **Preview & Deep-Linking**: Integrated PDF viewer that opens directly to the specific page and highlights the relevant paragraph.

![Search Sequence](/docs/images/admin/architecture/search-sequence.png)

## Research Assistant

The Research Assistant is a chat-based AI agent that answers questions about your document collection by searching, analyzing, and synthesizing evidence with full citations.

![Research Assistant](/docs/images/assistant/assistant-response.png)

### How It Works

The assistant uses a LangGraph-based agent loop powered by the [deepagents](https://github.com/krrome/deepagents) framework. When you ask a question, the agent:

1. **Plans** search queries to find relevant evidence across the document collection
2. **Searches** using the same hybrid retrieval pipeline (dense + sparse + reranking) as the main search
3. **Synthesizes** a structured, cited response with inline reference numbers
4. **Provides sources** — each citation links back to the specific document and page

Responses are streamed in real time via Server-Sent Events (SSE), so you see the agent's progress as it plans, searches, and writes.

### Normal Mode vs Deep Research

* **Normal mode** (`build_research_agent`) uses `create_agent` with a single agent loop. The agent has access to a `search_documents` tool and iterates until it has enough evidence to answer. This is fast and suitable for most questions.

* **Deep Research mode** (`build_deep_research_agent`) uses `create_deep_agent` with a LangChain-powered coordinator/researcher sub-agent architecture. A coordinator agent plans the investigation and delegates specific research tasks to specialist researcher sub-agents, each with their own `search_documents` tool. This enables more thorough, multi-step investigations with higher search limits. Both modes are config-driven — `max_queries`, `recursion_limit`, and `max_search_results` are set in `config.json`.

Toggle between modes with the **Deep research** checkbox below the chat input.

### Features

* **Multi-turn conversations** — follow-up questions maintain context within a thread
* **Thread history** — authenticated users can save, rename, and revisit past conversations
* **Inline citations** — numbered references link each claim to specific document chunks with page numbers
* **Expandable references** — click to expand the full reference list with document titles and page links
* **Star ratings** — rate assistant responses to provide feedback on quality
* **Configurable models** — the assistant respects the model selection in the top bar (Azure Foundry, Huggingface, etc.)
* **Search settings passthrough** — dense/sparse weights, reranking, field boost, and recency boost settings from the Search Settings panel are forwarded to the assistant's search tool

### API

* `POST /assistant/chat/stream` — SSE endpoint that streams the assistant response
* `GET /assistant/threads` — list saved conversation threads
* `GET /assistant/threads/{id}` — retrieve a thread with its messages
* `POST /assistant/threads/{id}/rename` — rename a thread
* `DELETE /assistant/threads/{id}` — delete a thread

## Administration & Observability

Tools for managing the pipeline and data quality.

* **Documents Dashboard**: Visual breakdown of the corpus by Agency, Year, Type, and Language.
* **Data Grid**: Filterable table of all documents with status tracking (`Indexed`, `Error`, `Parsed`) and direct Web/PDF links.
* **Inspection Tools**:
  * **Chunk Inspector**: View the raw JSON, text, and vector content of any document chunk to debug indexing issues.
  * **TOC Editor**: Inspect and adjust the inferred section classifications from the Table of Contents.
* **Pipeline Controls**: Manually re-trigger the processing pipeline for specific documents directly from the UI.
* **Traceability**: Full visibility into processing errors, including raw error logs and stack traces preserved in the database.

## Optimization

The platform has been designed to run in Docker, however some pipeline tasks benefit from hardware accepleration that Docker doesn't always provide. For example parsing can leverage GPUs and MPS acceleration. For the large volumes of data on [https://evidencelab.ai](https://evidencelab.ai), the pipeline was run on the host of a M4 Mac Mini with 7 parallel threads using [`/scripts/pipeline/run_pipeline_host.sh`]([`/scripts/pipeline/run_pipeline_host.sh`]).

Another area for optimization is with the Qdrant vector database. Though it works perfectly well inside Docker, for best IO performance on [https://evidencelab.ai](https://evidencelab.ai) it is run on the host with int8 quantized vectors in-memory.

## AI Models

### Pipeline

The pipeline utilizes AI models in a few places:

- Vector embeddings, used for search
- LLM document summarization
- LLM tagging
- LLM Document Structure analysis

Above you can see a menu options for models. The demo data was processed using the specified Huggingface models, with an additional generation of vectors using Azure Foundry. The latter is so users can try two different embedding models in the user interface.

### User Interface

As shown in the above models drop-down, this user interface can use either open models found on Huggingface or Azure foundry (Azure open AI). Over time, more will be added.

One thing to note, is that if using Huggingface models, the search reranker model runs locally on the application host. Since this project aims for low-cost, using such a model will result in slow search queries as the host isn't that powerful. With more work and engineering (and hosting cost) this could be addressed in future.

## AI Prompts

All AI-driven processes in Evidence Lab are controlled by **Jinja2 prompt templates** stored in the `prompts/` directory. This makes it straightforward to customize AI behavior without changing application code.

### Prompt Templates

| Template | Purpose |
|---|---|
| `assistant_system.j2` | Research Assistant system prompt — controls how the agent searches and synthesizes responses |
| `assistant_deep_research_coordinator.j2` | Deep Research coordinator prompt — orchestrates sub-agent delegation |
| `assistant_deep_research_researcher.j2` | Deep Research researcher sub-agent prompt — executes focused search tasks |
| `ai_summary_system.j2` / `ai_summary_user.j2` | AI search summary generation — the summary shown above search results |
| `summary_reduction.j2` / `summary_final.j2` | Document summarization — Map-Reduce pipeline for generating document abstracts |
| `toc_classification_system.j2` / `toc_classification_user.j2` | Section classification — categorizes document sections (findings, methodology, etc.) |
| `toc_category_judge.j2` | Section classification judge — resolves ambiguous classifications |
| `toc_extract_from_page.j2` / `toc_validation.j2` | Table of Contents extraction and validation |
| `taxonomy_sdg_system.j2` / `taxonomy_sdg_user.j2` | SDG taxonomy classification |
| `taxonomy_cross_cutting_theme_system.j2` / `taxonomy_cross_cutting_theme_user.j2` | Cross-cutting theme classification |
| `semantic_highlight_system.j2` / `semantic_highlight_user.j2` | Semantic highlighting of search result snippets |
| `search_evals_judge_relevance_user.j2` | Search quality evaluation — judges result relevance |
| `search_tests_*.j2` | Search test generation — creates test queries and verifies results |

### Group-Level Prompt Overrides

Administrators can override the AI search summary prompt on a per-group basis via the **Admin Panel → Group Settings**. This allows different user groups to receive responses tailored to their needs — for example, a technical group might receive more detailed citations while a policy group gets higher-level summaries.

The override system uses a two-layer approach:
1. **Built-in templates** (code-level) — the Jinja2 files in `prompts/` serve as the defaults
2. **Group overrides** (database) — stored in the `UserGroup.summary_prompt` field and editable from the admin UI

When a group has a custom prompt, it replaces the default system prompt for AI summary generation. If the override is cleared, the system falls back to the built-in template.

## User Authentication & Permissions

The authentication module is opt-in and built on [fastapi-users](https://fastapi-users.github.io/fastapi-users/) for industry-standard authentication patterns. It supports three modes via the `USER_MODULE` environment variable: `off` (default, no auth), `on_passive` (auth available but optional — anonymous users can browse freely), and `on_active` (all access requires login). It is designed with future MFA support in mind.

### Authentication

* **Email/password registration** with mandatory email verification before first sign-in. Passwords are hashed with bcrypt and must meet configurable complexity rules (minimum length, at least one letter and one digit).
* **OAuth single sign-on** with Google and Microsoft — users are auto-linked by email so an OAuth user who later sets a password (or vice versa) shares a single account.
* **Cookie-based sessions** using httpOnly, secure, SameSite cookies. No tokens are stored in localStorage, eliminating XSS token-theft risk.
* **CSRF protection** via the double-submit cookie pattern — a non-httpOnly `evidencelab_csrf` cookie is read by the frontend and echoed as the `X-CSRF-Token` header on every state-changing request.

### Security

* **Account lockout** — after a configurable number of consecutive failed login attempts (default 5), the account is locked for a configurable period (default 15 minutes).
* **Rate limiting** — login, registration, and password-reset endpoints are rate-limited per IP address to mitigate brute-force and credential-stuffing attacks.
* **Audit logging** — all security-relevant events (login success/failure, registration, password reset, account deletion) are recorded in an append-only audit log with timestamp, user, and IP address.
* **Domain restriction** — registration can optionally be restricted to approved email domains via `AUTH_ALLOWED_EMAIL_DOMAINS`.

### Permissions

* **Group-based access control** — users belong to one or more groups, each of which is granted access to specific data-source keys. Searches and document views are filtered so users only see data sources their groups allow.
* **Default group** — new users are automatically added to a configurable default group so they have baseline access without admin intervention.
* **Admin panel** — superusers can manage users (activate, verify, promote), create and edit groups, and assign data-source access from the UI. The first admin is bootstrapped via the `FIRST_SUPERUSER_EMAIL` environment variable.

### User Feedback & Activity

* **Ratings** — authenticated users can rate search results, AI summaries, document summaries, and taxonomy tags on a 1–5 star scale with optional comments. Ratings are stored in the `user_ratings` table with upsert semantics (one rating per user per type per reference per item).
* **Activity logging** — every search by an authenticated user is automatically logged to the `user_activity` table, including the query, filters, first-page results (lean payload), AI summary (appended after streaming completes), and the page URL. Activity records are linked by a UUID search ID.
* **Admin views** — the admin panel includes Ratings and Activity tabs with search, sort, pagination, and XLSX export.
* **API endpoints**:
  * `POST /ratings/` — create or update a rating (upsert)
  * `GET /ratings/mine` — retrieve the current user's ratings (optionally filtered by type/reference)
  * `DELETE /ratings/{id}` — delete a specific rating
  * `GET /ratings/all` — admin: paginated list of all ratings
  * `GET /ratings/export` — admin: XLSX download
  * `POST /activity/` — log a search activity event
  * `PATCH /activity/{search_id}/summary` — append AI summary to an activity record
  * `GET /activity/all` — admin: paginated list of all activity
  * `GET /activity/export` — admin: XLSX download
* **Data lifecycle** — both tables use `ON DELETE CASCADE` on the `user_id` foreign key, so all ratings and activity are automatically deleted when a user account is removed.

### Security

For full details on security architecture, automated scanning, container security, and development practices, see [SECURITY.md](https://github.com/dividor/evidencelab/blob/main/SECURITY.md). This covers defense-in-depth measures including pre-commit hooks (Bandit, Gitleaks, Hadolint), CI/CD security jobs (pip-audit, npm audit, Trivy container scanning), CORS configuration, rate limiting, API key authentication, and the active authentication enforcement middleware.

### User self-service

* **Profile management** — users can update their display name from the Profile modal.
* **Account deletion** — users can permanently delete their account, which removes group memberships, OAuth links, ratings, activity logs, and anonymises audit log entries (user_id set to NULL while preserving the security record).
* **Privacy policy** — linked from the registration form; covers data collected, cookies, user rights, and retention periods.

## REST API

Evidence Lab exposes a REST API for programmatic access to search, documents, AI summaries, and more. The API is built on FastAPI and provides interactive Swagger documentation at `/api/docs`.

### Authentication

All data endpoints require an `X-API-Key` header. Keys can be set globally via the `API_SECRET_KEY` environment variable or generated by administrators from the **API Keys** tab in the admin panel. Logged-in UI users authenticate automatically via session cookies.

See [API](/docs/admin/api-keys) for full details on key management and usage examples.

## Technical Foundation

* **Containerized Architecture**: Fully dockerized.
* **Modern Frontend**: React + TypeScript.
* **Python Backend**: FastAPI + LangChain + Qdrant + Postgres.
