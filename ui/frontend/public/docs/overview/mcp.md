# Using in AI Platforms

Evidence Lab supports the Model Context Protocol (MCP), allowing AI assistants like Claude and ChatGPT to search and analyze evaluation documents directly from within your AI platform.

## What is MCP?

The Model Context Protocol is an open standard that enables AI assistants to interact with external tools and data sources. Evidence Lab's MCP server provides three tools for searching, retrieving, and analyzing evaluation documents.

## Connecting

### Claude (Desktop or Web)

1. Click **+** to open the connector menu
2. Select **Connectors > Manage Connectors**
3. Click **+** then **Add custom connector**
4. Enter a name (e.g. "Evidence Lab") and the MCP server URL for your instance
5. You will be prompted to log in with your Evidence Lab account

### ChatGPT

1. Click **+** then **More Add Sources**
2. Go to **Apps > Create Custom App**
3. Add a name and the MCP server URL for your instance
4. Authenticate with your Evidence Lab account when prompted

### Claude Code (CLI)

```bash
claude mcp add evidencelab --transport streamable-http \
  https://your-instance.example.com/api/mcp/
```

You will be prompted to authenticate via your browser.

## Available Tools

### `search`

Semantic search over chunked evaluation documents. Returns ranked text passages with metadata.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Natural language search query |
| `data_source` | string | "uneg" | Collection to search (e.g. "uneg", "worldbank") |
| `limit` | integer | 10 | Max results (1-100) |
| `filters` | object | null | Field filters (organization, year, country, etc.) |
| `section_types` | array | null | Restrict to section types (findings, recommendations, etc.) |
| `rerank` | boolean | false | Rerank with cross-encoder |
| `recency_boost` | boolean | false | Boost recent documents |
| `field_boost` | boolean | true | Apply field boosting |

### `get_document`

Retrieve full metadata for a specific document.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `doc_id` | string | *required* | Document identifier |
| `data_source` | string | "uneg" | Collection containing the document |

### `ask_assistant`

Ask the AI research assistant a question. The assistant searches documents, retrieves relevant passages, and synthesizes an answer with citations.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Research question |
| `data_source` | string | "uneg" | Collection to search |
| `deep_research` | boolean | false | Multi-pass deep research mode |

## Authentication

Connecting via the Claude or ChatGPT UI will prompt you to log in with your Evidence Lab account. For API or CLI access, use one of:

- **API Key**: Pass via `X-API-Key` header (generated in Admin > API Keys)
- **Bearer JWT**: Pass via `Authorization: Bearer <token>` header

## Rate Limits

| Tool | Default Limit |
|------|---------------|
| `search`, `get_document` | 30 requests/minute |
| `ask_assistant` | 10 requests/minute |

## Prompts

The server also provides prompt templates:

- **`research_question`**: Generates a structured prompt for investigating a topic
- **`comparative_analysis`**: Generates a prompt for comparing across organizations, countries, or other dimensions
