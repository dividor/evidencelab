# Using Evidence Lab in AI Platforms

Evidence Lab provides a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that allows AI assistants like Claude and ChatGPT to search and analyze evaluation documents directly from within their chat interfaces.

## Getting Started

To use Evidence Lab's MCP server, you need:

1. **A user account** on the Evidence Lab instance. You will be prompted to log in when you first connect.
2. **The MCP server URL** for your instance (e.g. `https://evidencelab.ai/mcp`)

When you connect from Claude or ChatGPT, you will be redirected to the Evidence Lab login page where you can sign in with your existing account (email/password, Microsoft, or Google) or register a new one.

## Connecting from Claude

### Claude Desktop

Add the following to your Claude Desktop configuration file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "evidencelab": {
      "url": "https://evidencelab.ai/mcp"
    }
  }
}
```

Restart Claude Desktop after saving. When you first use an Evidence Lab tool, you will be prompted to log in via your browser.

### Claude Code (CLI)

```bash
claude mcp add evidencelab --transport streamable-http \
  https://evidencelab.ai/mcp
```

## Connecting from ChatGPT

1. Open ChatGPT and navigate to **Settings > Connected Apps** (or use the MCP connection dialog)
2. Enter the MCP server URL: `https://evidencelab.ai/mcp`
3. When prompted, log in with your Evidence Lab account
4. The Evidence Lab tools will appear in your ChatGPT conversation

## Available Tools

### `search`

Semantic search over evaluation documents. Returns ranked text passages with document metadata, citations, and pre-formatted references.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Natural language search query |
| `data_source` | string | `"uneg"` | Collection to search |
| `limit` | integer | 10 | Max results (1-100) |
| `filters` | string (JSON) | null | Filter by organization, year, country, SDG, etc. |
| `section_types` | array | null | Restrict to specific sections (findings, recommendations, etc.) |
| `include_facets` | boolean | false | Return available filter values with counts |
| `rerank` | boolean | false | Rerank results with cross-encoder |
| `recency_boost` | boolean | false | Boost more recent documents |

Use `include_facets=true` on your first search to discover available filter values (organizations, years, countries, SDGs) and their document counts.

### `get_document`

Retrieve full metadata for a specific document found in search results.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `doc_id` | string | *required* | Document identifier (from search results) |
| `data_source` | string | `"uneg"` | Collection containing the document |

### `ask_assistant`

Ask the AI research assistant a question. The assistant searches documents, retrieves relevant passages, and synthesizes a comprehensive answer with inline citations.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Research question |
| `data_source` | string | `"uneg"` | Collection to search |
| `deep_research` | boolean | false | Multi-pass deep research mode (slower, more thorough) |

## Data Sources

Available data sources depend on your Evidence Lab instance configuration. The default instance includes:

- **uneg** - UN Humanitarian Evaluation Reports (~15,000 documents from 20+ UN agencies)
- **worldbank** - World Bank Fraud and Integrity Reports
- **unmandates** - UN Mandates Registry (~4,000 resolutions and decisions)

## Prompt Templates

The server provides prompt templates to help structure research:

- **`research_question`** - Generates a structured prompt for investigating a topic
- **`comparative_analysis`** - Generates a prompt for comparing across organizations, countries, or time periods

## Rate Limits

| Tool | Default Limit |
|------|---------------|
| `search`, `get_document` | 30 requests/minute |
| `ask_assistant` | 10 requests/minute |

## Example Usage

Once connected, you can ask your AI assistant questions like:

- *"Search Evidence Lab for evaluations about climate adaptation in East Africa"*
- *"What do UN evaluations say about the effectiveness of school feeding programs?"*
- *"Find World Bank integrity reports related to procurement fraud"*
- *"Compare how UNDP and UNICEF approach gender mainstreaming in their evaluations"*

The assistant will use the Evidence Lab tools automatically to search documents, retrieve relevant passages, and provide answers with citations linking back to the original evaluation reports.
