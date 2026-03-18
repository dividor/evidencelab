# Changelog

All notable changes to Evidence Lab will be documented in this file.

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
