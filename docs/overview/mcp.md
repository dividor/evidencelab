# Connecting to AI Platforms

Evidence Lab can be connected to AI platforms and agent frameworks via two open protocols:

| | MCP | A2A |
|---|---|---|
| **Protocol** | Model Context Protocol | Agent-to-Agent |
| **Used by** | LLMs (Claude, ChatGPT) calling tools | AI agents delegating full research tasks |
| **Returns** | Raw passages, document metadata | Synthesised answers with citations |
| **URL** | `/mcp` | `/a2a` |
| **Auth** | OAuth 2.0 or API Key | API Key or Bearer token |

---

## MCP Server

Evidence Lab supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/), allowing AI assistants like Claude and ChatGPT to search and retrieve evaluation documents directly from within your AI platform.

### Connecting Claude

In the Claude desktop or web app:

1. Click **+** → **Connectors** → **Manage Connectors**
2. Click **+** → **Add custom connector**
3. Enter a name (e.g. *Evidence Lab*) and the URL: `https://evidencelab.ai/mcp`
4. You will be prompted to log in with your Evidence Lab account

### Connecting ChatGPT

In ChatGPT:

1. Click **+** → **More Add Sources**
2. Click **Apps** → **Create Custom App**
3. Enter a name and the URL: `https://evidencelab.ai/mcp`

### Available tools

#### `search`

Semantic search over evaluation document chunks. Returns ranked text passages with metadata, citations, and source links.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | *required* | Natural language search query |
| `data_source` | `"uneg"` | Collection: `"uneg"`, `"worldbank"`, `"unmandates"` |
| `limit` | `10` | Max results (1–100) |
| `filters` | `null` | Field filters — `{"organization": "UNDP", "published_year": "2024"}` |
| `section_types` | `null` | Restrict to section types: `"findings"`, `"recommendations"`, etc. |
| `include_facets` | `false` | Return available filter values and counts |

#### `get_document`

Retrieve full metadata for a specific document by ID.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `doc_id` | *required* | Document identifier (from search results) |
| `data_source` | `"uneg"` | Collection containing the document |

### Authentication

Evidence Lab uses OAuth 2.0. When you add the connector, Claude and ChatGPT will prompt you to log in via the Evidence Lab login page. Your session is stored securely — you will not be asked again unless your session expires.

### Testing with MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

Connect to `https://evidencelab.ai/mcp` and authenticate with your API key (`X-API-Key` header) to browse available tools and run queries.

---

## A2A Server

Evidence Lab implements the [Agent-to-Agent (A2A) protocol](https://a2a-protocol.org/), allowing AI agent frameworks (Google ADK, CrewAI, LangGraph, Azure AI Foundry, etc.) to delegate research tasks directly to Evidence Lab and receive synthesised answers.

Where MCP exposes *tools* for an LLM to call, A2A exposes an *agent* that handles the entire research workflow — searching, synthesising, and returning a complete answer with citations.

### Connecting

The A2A endpoint and Agent Card:

```
POST  https://evidencelab.ai/a2a
GET   https://evidencelab.ai/.well-known/agent.json
```

Any A2A-compatible orchestrator can discover Evidence Lab's skills automatically from the Agent Card URL.

### Skills

#### `research`

Ask a research question. The assistant searches across the document collection, synthesises findings, and returns a comprehensive answer with inline citations.

**Example inputs:**
- *"What are the main findings on climate adaptation in Africa?"*
- *"How effective have school feeding programs been?"*
- *"Compare approaches to gender mainstreaming across UN agencies"*

**Metadata parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `skill` | auto | Set to `"research"` to force this skill |
| `data_source` | `"uneg"` | Collection: `"uneg"`, `"worldbank"`, `"unmandates"` |
| `deep_research` | `false` | Multi-pass research mode for complex questions |

#### `search`

Semantic search returning raw document passages. Use when the calling agent wants to analyse the evidence itself.

**Metadata parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `skill` | auto | Set to `"search"` to force this skill |
| `data_source` | `"uneg"` | Collection to search |
| `limit` | `10` | Max results (1–100) |
| `filters` | `null` | JSON field filters — `{"organization": "UNICEF", "published_year": "2023"}` |

> **Skill selection:** if `skill` is not set, messages starting with "Search" route to `search`; everything else routes to `research`.

### Sending a task

```http
POST https://evidencelab.ai/a2a
Content-Type: application/json
X-API-Key: <key>

{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "What does the evidence say about cash transfer programs?"}],
      "metadata": {"skill": "research", "data_source": "uneg"}
    }
  }
}
```

For streaming (token-by-token), use `message/stream` with `Accept: text/event-stream`.

### Authentication

All A2A requests require authentication via `X-API-Key: <key>` or `Authorization: Bearer <token>`. Generate an API key from **Admin → API Keys**.

### Testing with A2A Inspector

```bash
npx a2a-inspector
```

Connect to `https://evidencelab.ai/.well-known/agent.json` and set the `X-API-Key` header. The inspector loads the Agent Card, shows available skills, and lets you send tasks and inspect responses.
