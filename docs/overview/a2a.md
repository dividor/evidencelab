# Agent-to-Agent (A2A) Server

Evidence Lab implements the [Google Agent-to-Agent (A2A) protocol](https://google.github.io/A2A/), allowing other AI agents to delegate research tasks directly to Evidence Lab.

## What is A2A?

The Agent-to-Agent protocol is an open standard for AI agent interoperability. Where MCP exposes *tools* that an LLM can call within its context window, A2A exposes an *agent* that other agents can delegate entire tasks to — receiving a complete answer back, rather than raw tool results.

In practical terms:
- **MCP** — you connect Claude or ChatGPT and they call `search` or `get_document` to retrieve raw passages you analyse yourself
- **A2A** — an orchestrating agent sends a research question and Evidence Lab's assistant handles the full research workflow, returning a synthesised answer with citations

## Connecting

The Evidence Lab A2A agent is available at:

```
https://evidencelab.ai/a2a
```

The Agent Card (machine-readable capability descriptor) is at:

```
https://evidencelab.ai/.well-known/agent.json
```

Any A2A-compatible orchestrator (Google ADK, CrewAI, LangGraph, etc.) can discover Evidence Lab's skills automatically from the Agent Card URL.

## Skills

Evidence Lab exposes two A2A skills:

### `research`

Ask a research question. The assistant searches across the document collection, synthesises findings from multiple relevant passages, and returns a comprehensive answer with inline citations and links to source documents.

**Example inputs:**
- *"What are the main findings on climate adaptation in Africa?"*
- *"How effective have school feeding programs been?"*
- *"Compare approaches to gender mainstreaming across UN agencies"*

**Returns:** A text answer with inline citations, plus a structured data artifact containing the citation list, references, and source document metadata.

**Optional metadata parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `data_source` | `"uneg"` | Collection to search: `"uneg"`, `"worldbank"`, `"unmandates"` |
| `deep_research` | `false` | Multi-pass research mode for complex questions |
| `model_combo` | `"Azure Foundry"` | Model configuration |

### `search`

Semantic search returning raw document passages. Use this when the calling agent wants to analyse the evidence itself rather than receive a synthesised answer.

**Example inputs:**
- *"Search for findings on food security in Yemen"*
- *"Search uneg for WASH recommendations {"organization": "UNICEF"}"*

**Returns:** A text summary of results plus a structured data artifact with the full result list, scores, metadata, and citations.

**Optional metadata parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `data_source` | `"uneg"` | Collection to search |
| `limit` | `10` | Max results (1–100) |
| `filters` | `null` | JSON object with field filters (organization, year, country, etc.) |
| `model_combo` | `"Azure Foundry"` | Model configuration |

## Sending a task

Tasks are submitted as JSON-RPC over HTTP. To specify which skill to use, either:

1. **Metadata** — set `skill` in the message metadata: `{"skill": "research"}` or `{"skill": "search"}`
2. **Auto-detect** — if no skill is specified, a message starting with "Search" routes to `search`, everything else to `research`

**Example — synchronous research task:**

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

**Example — streaming task (SSE):**

```http
POST https://evidencelab.ai/a2a
Content-Type: application/json
Accept: text/event-stream
X-API-Key: <key>

{
  "jsonrpc": "2.0",
  "id": "req-2",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "Compare gender mainstreaming across UNDP and UNICEF evaluations"}],
      "metadata": {"skill": "research", "deep_research": true}
    }
  }
}
```

Streaming returns a sequence of JSON-RPC SSE events:
- `status-update` — state changes (submitted → working → completed)
- `artifact-update` — token-by-token text as it is generated

## Authentication

All A2A requests require authentication. The same methods as MCP are supported:

- **API Key** — `X-API-Key: <key>` header
- **Bearer token** — `Authorization: Bearer <token>` header (JWT or OAuth access token)

## Testing with A2A Inspector

You can test the Evidence Lab A2A agent interactively using the [A2A Inspector](https://github.com/a2aproject/a2a-inspector):

```bash
npx a2a-inspector
```

Connect to `https://evidencelab.ai/.well-known/agent.json` and set the `X-API-Key` header with your API key. The inspector will load the Agent Card, display available skills, and let you send tasks and inspect responses.

## Relationship to MCP

MCP and A2A run on the same Evidence Lab service and share the same authentication:

| | MCP | A2A |
|---|---|---|
| Protocol | Model Context Protocol | Agent-to-Agent |
| Called by | LLMs (Claude, ChatGPT) as tools | AI agents as task delegation |
| Returns | Raw passages, document metadata | Synthesised answers |
| Streaming | Stateless HTTP | SSE task events |
| URL | `/mcp` | `/a2a` |
| Skills/Tools | `search`, `get_document` | `research`, `search` |
