# Using in AI Platforms

Evidence Lab supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/), allowing AI assistants like Claude and ChatGPT to search and analyse evaluation documents directly from within your AI platform.

For AI agent frameworks (Google ADK, CrewAI, LangGraph, etc.) that need to delegate research tasks to Evidence Lab, see [Agent-to-Agent (A2A) Server](a2a.md).

## Connecting Claude

In the Claude desktop or web app:

1. Click **+** → **Connectors** → **Manage Connectors**
2. Click **+** → **Add custom connector**
3. Enter a name (e.g. *Evidence Lab*) and the URL: `https://evidencelab.ai/mcp`
4. You will be prompted to log in with your Evidence Lab account

## Connecting ChatGPT

In ChatGPT:

1. Click **+** → **More Add Sources**
2. Click **Apps** → **Create Custom App**
3. Enter a name and the URL: `https://evidencelab.ai/mcp`

## What you can do

Once connected, you can ask Claude or ChatGPT to search Evidence Lab directly in your conversation:

- *"Search Evidence Lab for findings on climate adaptation in Africa"*
- *"What UNICEF evaluations are available on education from 2022–2024?"*
- *"Find recommendations on WASH programming from WFP evaluations"*
- *"Get the full metadata for document ID xyz-123"*

## Available tools

### `search`

Semantic search over evaluation document chunks. Returns ranked text passages with metadata, citations, and source links.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | *required* | Natural language search query |
| `data_source` | `"uneg"` | Collection: `"uneg"`, `"worldbank"`, `"unmandates"` |
| `limit` | `10` | Max results (1–100) |
| `filters` | `null` | Field filters — `{"organization": "UNDP", "published_year": "2024"}` |
| `section_types` | `null` | Restrict to section types: `"findings"`, `"recommendations"`, etc. |
| `include_facets` | `false` | Return available filter values and counts |

### `get_document`

Retrieve full metadata for a specific document by ID.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `doc_id` | *required* | Document identifier (from search results) |
| `data_source` | `"uneg"` | Collection containing the document |

## Research synthesis

For synthesised narrative answers with citations — rather than raw search passages — use the Evidence Lab A2A agent. Any agent framework that supports A2A can delegate research questions to Evidence Lab and receive a full answer. See [Agent-to-Agent (A2A) Server](a2a.md).

## Data sources

| Collection | Contents |
|-----------|----------|
| `uneg` | ~15,000 UN humanitarian evaluation reports (UNDP, UNICEF, WFP, FAO, ILO and 20+ agencies, 1985–present) |
| `worldbank` | World Bank Integrity Vice Presidency investigation reports |
| `unmandates` | ~4,000 UN General Assembly, Security Council, and ECOSOC resolutions |

## Authentication

Evidence Lab uses OAuth 2.0. When you add the connector, Claude and ChatGPT will prompt you to log in via the Evidence Lab login page. Your session is stored securely — you will not be asked again unless your session expires.
