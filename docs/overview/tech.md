## Document Processing Pipeline

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

### User self-service

* **Profile management** — users can update their display name from the Profile modal.
* **Account deletion** — users can permanently delete their account, which removes group memberships, OAuth links, ratings, activity logs, and anonymises audit log entries (user_id set to NULL while preserving the security record).
* **Privacy policy** — linked from the registration form; covers data collected, cookies, user rights, and retention periods.

## Technical Foundation

* **Containerized Architecture**: Fully dockerized.
* **Modern Frontend**: React + TypeScript.
* **Python Backend**: FastAPI + LangChain + Qdrant + Postgres.

## Configuring Evidence Lab for Your Documents

For more detailed instructions refer to the [Evidence Lab GitHub Repo](https://github.com/dividor/evidencelab).

1. **Configure data sources**
   - Edit [`config.json`](https://github.com/dividor/evidencelab/blob/main/config.json) in the repo root to define `datasources`, `data_subdir`, and `field_mapping`, along with fields to control how your documents are parsed.
   - The UI reads the same `config.json` via Docker Compose.

2. **Set environment variables**
   - Copy [`.env.example`](https://github.com/dividor/evidencelab/blob/main/.env.example) to `.env`.
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
             report_124.error (optional, if download failed)
   ```

4. **Run the pipeline (Docker)**
   ```bash
   # Start services
   docker compose up -d --build

   # Run the orchestrator (example: UNEG)
   docker compose exec pipeline \
     python -m pipeline.orchestrator --data-source uneg --skip-download --num-records 10
   ```

5. **Access the Evidence Lab UI**
   - Open http://localhost:3000
   - Select your data source and search the indexed documents

For more detailed information see the [Evidence Lab GitHub Repo](https://github.com/dividor/evidencelab).
