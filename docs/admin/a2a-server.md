# A2A Server Administration

The A2A (Agent-to-Agent) server runs as part of the same Docker service as the MCP server (`mcp` container, port 8001). It implements the [Google A2A protocol](https://google.github.io/A2A/) and shares the same auth, rate limiting, and service code.

## Architecture

```
Orchestrating Agent (Google ADK, CrewAI, LangGraph, etc.)
  |
  | POST /a2a  (JSON-RPC)
  v
nginx (/a2a -> http://mcp:8001/a2a)
  |
  v
A2A Server (a2a_server/)
  |
  +-- research skill --> mcp_server/tools/assistant.py
  |                         --> ui/backend/services/assistant_service.py
  |
  +-- search skill  --> mcp_server/tools/search.py
                           --> ui/backend/services/search.py
                           --> Qdrant + PostgreSQL
```

The A2A server (`a2a_server/`) imports the same tool modules as MCP — no duplicate service calls or logic.

## Endpoints

| Endpoint | Method | Auth required | Description |
|----------|--------|---------------|-------------|
| `/.well-known/agent.json` | GET | No | Agent Card (capability descriptor) |
| `/a2a` | POST | Yes | JSON-RPC task endpoint |

### Agent Card

The Agent Card is served at `/.well-known/agent.json` and is generated at runtime from `config.json` — the `name`, `description`, and skill descriptions reflect the datasources actually configured.

```bash
curl https://evidencelab.ai/.well-known/agent.json | jq .
```

Example response (fields vary by instance configuration):

```json
{
  "name": "Evidence Lab Research Agent",
  "description": "AI research agent for UN Humanitarian Evaluation Reports, World Bank Fraud and Integrity Reports, and UN Mandates Registry. Searches document collections and synthesises answers with source citations.",
  "url": "https://evidencelab.ai/a2a",
  "version": "1.0.0",
  "protocolVersion": "1.0",
  "preferredTransport": "JSONRPC",
  "capabilities": { "streaming": true, "pushNotifications": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "authentication": { "schemes": ["Bearer", "ApiKey"] },
  "documentationUrl": "https://evidencelab.ai/docs",
  "skills": [
    {
      "id": "research",
      "name": "Research Evaluations",
      "description": "Answer research questions across: UN Humanitarian Evaluation Reports; World Bank Fraud and Integrity Reports; UN Mandates Registry. Returns a synthesised answer with inline citations and links to source documents.",
      "tags": ["research", "evaluations", "evidence"]
    },
    {
      "id": "search",
      "name": "Search Evaluation Documents",
      "description": "Semantic search over document chunks. Returns ranked text passages with metadata.",
      "tags": ["search", "evaluations", "semantic"]
    }
  ]
}
```

## Configuration

### Environment Variables

A2A shares all environment variables with the MCP server. No additional variables are required.

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_BASE_URL` | `https://evidencelab.ai` | Base URL embedded in the Agent Card `url` field |
| `REQUIRE_API_KEY` | `true` | Require auth on `/a2a` requests |
| `RATE_LIMIT_MCP_AI` | `10/minute` | Rate limit applied to research skill |
| `RATE_LIMIT_MCP_SEARCH` | `30/minute` | Rate limit applied to search skill |

### Nginx Proxy

Add alongside the `/mcp` proxy block:

```nginx
location /a2a {
    proxy_pass http://mcp:8001/a2a;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
    # Required for SSE streaming (tasks/sendSubscribe)
    proxy_buffering off;
    proxy_cache off;
}

location /.well-known/agent.json {
    proxy_pass http://mcp:8001/.well-known/agent.json;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
}
```

> **Important:** `proxy_buffering off` is required for `tasks/sendSubscribe` — without it nginx buffers the SSE stream and the client receives nothing until the response completes.

## JSON-RPC Methods

Both A2A v1.0 and legacy method names are accepted:

| v1.0 method | Legacy method | Description |
|-------------|---------------|-------------|
| `message/send` | `tasks/send` | Submit a task and wait for the completed result (synchronous) |
| `message/stream` | `tasks/sendSubscribe` | Submit a task and receive streaming SSE events |
| — | `tasks/get` | Retrieve a previously submitted task by ID |
| — | `tasks/cancel` | Cancel a task (only tasks that have not yet completed) |

### Error codes

| Code | Name | Description |
|------|------|-------------|
| `-32700` | Parse error | Invalid JSON in request body |
| `-32600` | Invalid request | JSON-RPC envelope is malformed |
| `-32601` | Method not found | Unknown method name |
| `-32602` | Invalid params | Method params failed validation |
| `-32603` | Internal error | Unhandled server error |
| `-32001` | Task not found | `tasks/get` or `tasks/cancel` for an unknown task ID |
| `-32004` | Unsupported operation | e.g. cancel a completed task, or SSE without `Accept: text/event-stream` |

## Task Lifecycle

```
submitted → working → completed
                    → failed
                    → canceled
```

Tasks are held in memory for the lifetime of the container process. Task IDs are unique per request; if you need persistence across restarts, supply your own `id` and handle re-submission on your side.

## Skills

### `research`

Invokes the Evidence Lab research assistant. The assistant:
1. Generates multiple search queries from the input question
2. Retrieves the most relevant document passages from Qdrant
3. Synthesises a comprehensive answer with inline citations
4. Returns the answer as a `TextPart` and a structured `DataPart` containing citation metadata

**Metadata parameters accepted in the task message:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data_source` | string | `null` | Collection: `"uneg"`, `"worldbank"`, `"unmandates"` |
| `deep_research` | boolean | `false` | Multi-pass research mode |
| `model_combo` | string | `"Azure Foundry"` | Model configuration |
| `skill` | string | auto | Force skill selection: `"research"` or `"search"` |

### `search`

Runs the same hybrid semantic search as the MCP `search` tool. Returns raw passages ranked by relevance.

**Metadata parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data_source` | string | `null` | Collection to search |
| `limit` | integer | `10` | Max results (1–100) |
| `filters` | object | `null` | Field/value filter pairs |
| `model_combo` | string | `"Azure Foundry"` | Model configuration |
| `skill` | string | auto | Set to `"search"` to force this skill |

## Streaming (message/stream)

For long-running research tasks, use `message/stream` with `Accept: text/event-stream`. Each SSE line is a full JSON-RPC response envelope:

```
data: {"jsonrpc":"2.0","id":"<rpc_id>","result":{"kind":"status-update","taskId":"...","contextId":"...","status":{"state":"working"},"final":false}}
```

Event sequence:

1. `kind: "status-update"`, `state: "working"`, `final: false` — immediately on receipt
2. `kind: "artifact-update"` — one event per token as the answer streams
3. `kind: "artifact-update"` — final event with complete answer + citation `DataPart`
4. `kind: "status-update"`, `state: "completed"`, `final: true`

On error:
- `kind: "status-update"`, `state: "failed"`, `final: true` with an error message in the status message field

## Authentication

A2A uses the same auth middleware as MCP. See [MCP Server Administration](mcp-server.md#authentication) for full details.

## Monitoring

### Logs

```bash
docker compose logs mcp -f
```

A2A requests are logged at INFO level with the RPC method and task ID:

```
INFO [a2a_server.app] A2A RPC id=req-1 method=tasks/send
```

### Health

```bash
curl https://your-instance.example.com/mcp/health
```

The health endpoint is shared with MCP — a healthy response confirms both servers are ready.

## Troubleshooting

### Agent Card returns wrong URL

Ensure `APP_BASE_URL` is set to the externally-accessible domain. The Agent Card `url` field is built from this value.

### SSE stream not received

- Verify nginx has `proxy_buffering off` on the `/a2a` location block
- Confirm the client sends `Accept: text/event-stream`
- The `/a2a` endpoint returns a `400` JSON-RPC error (code `-32004`) if `text/event-stream` is not in `Accept`

### Research skill returns model errors

The research skill uses the assistant service which requires Azure OpenAI (default) or another configured LLM. Verify `AZURE_FOUNDRY_API_KEY` and `AZURE_FOUNDRY_ENDPOINT` are set, or configure an alternative `model_combo`.
