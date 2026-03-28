# Model Context Protocol (MCP) Server

Evidence Lab exposes an MCP server that allows AI assistants like Claude to search and analyze evaluation documents programmatically.

## What is MCP?

The Model Context Protocol is an open standard that enables AI assistants to interact with external tools and data sources. Evidence Lab's MCP server provides three tools for searching, retrieving, and analyzing evaluation documents.

## Connecting

### Claude Desktop

Add the following to your Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "evidencelab": {
      "url": "https://your-instance.example.com/api/mcp/",
      "headers": {
        "X-API-Key": "your-api-key"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add evidencelab --transport streamable-http \
  https://your-instance.example.com/api/mcp/ \
  --header "X-API-Key: your-api-key"
```

## Available Tools

### `search`

Semantic search over chunked evaluation documents. Returns ranked text passages with metadata.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Natural language search query |
| `data_source` | string | null | Collection to search (e.g. "uneg", "worldbank") |
| `limit` | integer | 20 | Max results (1-100) |
| `filters` | object | null | Field filters (organization, year, country, etc.) |
| `section_types` | array | null | Restrict to section types (findings, recommendations, etc.) |
| `rerank` | boolean | true | Rerank with cross-encoder |
| `recency_boost` | boolean | false | Boost recent documents |
| `field_boost` | boolean | true | Apply field boosting |

### `get_document`

Retrieve full metadata for a specific document.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `doc_id` | string | *required* | Document identifier |
| `data_source` | string | null | Collection containing the document |

### `ask_assistant`

Ask the AI research assistant a question. The assistant searches documents, retrieves relevant passages, and synthesizes an answer with citations.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Research question |
| `data_source` | string | null | Collection to search |
| `deep_research` | boolean | false | Multi-pass deep research mode |

## Authentication

All MCP requests require authentication via one of:

- **API Key**: Pass via `X-API-Key` header
- **Bearer JWT**: Pass via `Authorization: Bearer <token>` header
- **Session Cookie**: Automatically sent by browsers with an active session

## Rate Limits

| Tool | Default Limit |
|------|---------------|
| `search`, `get_document` | 30 requests/minute |
| `ask_assistant` | 10 requests/minute |

Rate limits can be configured via environment variables `RATE_LIMIT_MCP_SEARCH` and `RATE_LIMIT_MCP_AI`.

## Prompts

The server also provides prompt templates:

- **`research_question`**: Generates a structured prompt for investigating a topic
- **`comparative_analysis`**: Generates a prompt for comparing across organizations, countries, or other dimensions
