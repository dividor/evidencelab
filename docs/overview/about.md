## Evidence Lab

![Evidence Lab Architecture](/docs/images/evidence-lab.png)

Evidence Lab is a free open source platform that provides a document pipeline, search, and AI-powered information discovery and evidence mining tools. The aim is to provide a quick start for those looking to use AI with their documents and a place where new ideas can be tested.

You can run the code yourself, or explore the online version at [evidencelab.ai](https://evidencelab.ai) which has so far been populated with about 20,000 United Nations humanitarian evaluation reports sourced from the [United Nations Evaluation Group](https://www.un.org/evaluations). See [Data](/data) for more information on these amazing documents.

Evidence Lab includes a built-in **Research Assistant** that uses AI agents to search, analyze, and synthesize findings from your documents with full citations. A **Deep Research** mode delegates to specialist sub-agents for more thorough multi-step investigations. See the [Research Assistant](/docs/using-evidence-lab/research-assistant) guide for details.

## Philosophy

Evidence Lab grew out of research work for the AstroBagel Blog. The core design principles are:

- **Runs on a desktop** — the full pipeline can process 20,000 30-page documents in a week for less than $50
- **Configurable** — point it at a folder of PDFs and configure via a single config.json
- **Progressive complexity** — start with simple parsing and layer on richer features (image annotation, reranking) later without re-processing
- **Model-agnostic** — supports both open-source and proprietary embedding and LLM models
- **Observable** — built-in tools for monitoring pipeline progress and exploring AI retrieval quality

Some lofty, often conflicting, goals!

Always a work in progress, and low-cost high-speed processing which runs on a desktop computer, does come with a few shortcuts. Parsing isn't perfect, performance isn't lighting speed, but the aim is to provide a good foundation to be improved upon later.

## Features

Evidence Lab document processing pipeline includes the following features:

### Processing pipeline

- PDF/Word parsing with Docling, to include document structure detection
- Footnote and references, images and table detection
- Basic table extraction, with support for more expensive processing as required
- AI-assisted document summarization
- AI-assisted tagging of documents
- Indexing with Open (Huggingface) or proprietary models (Azure foundry, but extensible)

### User interface

- Hybrid search with AI summary and reranking
- **Research Assistant** — chat-based AI agent that searches your documents, synthesizes findings into structured responses with inline citations, and supports multi-turn conversations with thread history
- **Deep Research mode** — enables a coordinator/researcher sub-agent architecture for more thorough, multi-step investigations across your document collection
- **Drilldown research** — highlight text or click "Find out more" to automatically drill into sub-topics, building an explorable research tree with query inheritance (root + parent context)
- Experimental features such as [Heatmapper](/?tab=heatmap&dataset=UN+Humanitarian+Evaluation+Reports&model=azure_small&model_combo=Azure+Foundry&hm_row=document_type&hm_col=published_year&hm_metric=documents&hm_sens=0.2&published_year=2021%2C2022%2C2023%2C2024%2C2025) for tracking trends in content
- Filtering by metadata, in-document section types
- Search and reranking settings to explore different models
- Semantic highlighting in search results
- Basic language translation
- PDF preview with in-document search
- **Configurable AI prompts** — all AI processes (summaries, tagging, research assistant) use editable Jinja2 prompt templates, with group-level overrides available via the admin panel
- Administration views to track pipeline, documents, performance and errors

### User Authentication & Permissions (opt-in)

Evidence Lab includes an optional user module that adds authentication and data-source-level access control. When enabled (`USER_MODULE=true`), the system supports:

- **Email/password registration** with email verification
- **OAuth login** with Google and Microsoft
- **User profiles** with display name and group membership
- **Group-based permissions** — admins can create groups and control which data sources each group can access
- **Admin panel** — manage users, groups, and data source assignments
- **User feedback** — rate search results, AI summaries, document summaries, and taxonomy tags with 1–5 stars and optional comments
- **Activity logging** — automatic logging of search queries and results for authenticated users, with admin views and XLSX export

The module is built on [fastapi-users](https://fastapi-users.github.io/fastapi-users/) for industry-standard authentication patterns and is designed with future MFA support in mind.

More features will be added soon, focused on document evidence analysis and MCP (Model Context Protocol) support.

For more detailed information on how the above features have been implemented, mosey on over to [Tech](/tech).

## Get involved

If you would like to have your public documents added to Evidence Lab for research, or would like to contribute to the project, please reach out to [evidencelab@astrobagel.com](mailto:evidencelab@astrobagel.com).

Also, for the latest news check out the [AstroBagel Blog](https://medium.com/@astrobagel).
