# Changelog

All notable changes to Evidence Lab will be documented in this file.

## [1.1.0] - 2026-03-10

### Research Assistant
- **New Research Assistant tab** — chat-based AI agent that searches, analyzes, and synthesizes findings from your documents with full inline citations
- **Deep Research mode** — coordinator/researcher sub-agent architecture using LangGraph and [deepagents](https://github.com/krrome/deepagents) for thorough multi-step investigations
- **Real-time streaming** — responses streamed via Server-Sent Events with live search progress, expandable result cards, and phase indicators
- **Multi-turn conversations** — follow-up questions maintain context within a thread
- **Thread history** — save, rename, search, and revisit past conversations
- **Inline citations** — numbered references at the end of each sentence link claims to specific document chunks with page numbers
- **Expandable references** — click to expand the full reference list with document titles and page links
- **Config-driven parameters** — `max_queries`, `recursion_limit`, and `max_search_results` configurable in `config.json` for both normal and deep research modes
- **Search settings passthrough** — dense/sparse weights, reranking, field boost, and recency boost forwarded to the assistant's search tool
- **Assistant ratings** — rate assistant responses with separate feedback types for basic and deep research

### Research Trees (Drilldown Research)
- **AI Summary drilldown** — highlight text or click "Find out more" to drill into sub-topics
- **Tree-based navigation** — explorable research tree with branching graph view
- **Query inheritance** — sub-queries inherit root search query plus parent context and all active filters
- **Batch research** — "Find out more" button to research all key facts at once
- **Save and load research** — persist research trees for later exploration
- **PDF export** — export research trees with global summary to PDF

### User Authentication & Permissions
- **Email/password registration** with mandatory email verification
- **OAuth single sign-on** with Google and Microsoft providers
- **Three authentication modes** — `off` (default), `on_passive` (optional login), `on_active` (login required)
- **Cookie-based sessions** with CSRF protection (no tokens in localStorage)
- **Account lockout and rate limiting** for brute-force protection
- **Audit logging** of all security-relevant events
- **Group-based data-source access control** — restrict which datasets users can see
- **Admin panel** for managing users, groups, and data-source assignments
- **Domain restriction** — optionally restrict registration to approved email domains
- **Self-service profile management** and account deletion
- **Privacy policy** with cookie consent banner
- **Branded email templates** for verification and password reset

### User Feedback & Activity
- **Star ratings** — rate search results, AI summaries, document summaries, taxonomy tags, and assistant responses (1-5 stars with optional comments)
- **Activity logging** — automatic capture of search queries, results, AI summaries, and assistant interactions for authenticated users
- **Admin views** — ratings and activity tabs with search, sort, pagination, and XLSX export
- **Separate rating types** — `assistant-basic` and `assistant-deep-research` for assistant feedback

### Search Enhancements
- **Field boosting** — detects countries/organizations in queries and promotes matching results; at full weight acts as a hard filter
- **Config-driven filter fields** — `filter_fields` in datasource config controls which fields appear in the filter panel
- **Cardinality validation** and range filters for numerical fields
- **Auto min score filtering** using percentile-based thresholding

### Documentation
- **Built-in documentation area** with searchable sidebar navigation, table of contents, and markdown rendering
- **About, Tech, and Data pages** now open in the doc viewer with full navigation
- **Research Assistant guide** with screenshots
- **AI Prompts documentation** covering all Jinja2 prompt templates and group-level overrides

### Pipeline Improvements
- **Tagger fixes** — auto-split oversized TOC payloads and summaries to fit context windows
- **Parser improvements** — better error handling for missing files
- **Indexer** — truncate oversized chunks to embedding model token limit
- **Sanitization** — NFD normalization before stripping non-ASCII characters
- **Refresh buttons** on Pipeline, Processing, and Stats screens

### AI Prompts
- **Configurable Jinja2 prompt templates** for all AI processes (summaries, tagging, research assistant)
- **Group-level prompt overrides** — administrators can customize the AI summary prompt per user group via the admin panel
- **Per-group search and content settings** — configure greeting messages, search parameters per group

### Administration
- **User management** — activate, verify, promote users; inline create-user form
- **Group management** — create/edit groups, assign data-source access, set greeting messages
- **Editable group names and descriptions**
- **Admin activity and ratings tabs** with XLSX export

### Infrastructure
- **Google Cloud Vertex AI support** for embeddings and LLMs
- **World Bank datasource** configuration with SDG taxonomy
- **Dynamic model combos** — filter UI model selections by actually indexed models
- **Anonymous activity tracking** for non-logged-in users
- **Maintenance scripts** for comparing downloads and restoring Qdrant backups

## [1.0.0] - 2025-12-01

Initial release of Evidence Lab with document processing pipeline, hybrid search, AI summaries, heatmapper, and administration tools.
