# MCP Server Administration

The MCP server runs as a separate Docker service that exposes Evidence Lab's search tools via the [Model Context Protocol](https://modelcontextprotocol.io/). The same service also hosts the [A2A Server](a2a-server.md) for agent-to-agent research tasks.

> **Tools:** `search` and `get_document` only. Research synthesis is handled by the [A2A Server](a2a-server.md).

## Architecture

The MCP server is a standalone Python service (`mcp_server/`) that imports Evidence Lab's search and assistant services directly. It runs alongside the API server but on its own port (default 8001), with nginx proxying `/mcp` to it.

```
Client (Claude/ChatGPT)
  |
  v
nginx (/mcp -> http://mcp:8001/mcp)
  |
  v
MCP Server (Streamable HTTP transport)
  |
  v
Evidence Lab Services (search, assistant, document retrieval)
  |
  v
Qdrant + PostgreSQL
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_PORT` | `8001` | Port the MCP server listens on |
| `API_SECRET_KEY` | *required* | Shared secret for API key authentication |
| `AUTH_SECRET_KEY` | *required* | Secret for JWT token verification |
| `APP_BASE_URL` | `https://evidencelab.ai` | Base URL for OAuth redirects and citation links |
| `OAUTH_CALLBACK_BASE_URL` | `http://localhost:8000` | Base URL for OAuth callbacks |
| `RATE_LIMIT_MCP_SEARCH` | `30/minute` | Rate limit for search and get_document tools |
| `RATE_LIMIT_MCP_AI` | `10/minute` | Rate limit for ask_assistant tool |

### Docker Compose

The MCP server is defined as the `mcp` service in `docker-compose.yml`. It shares the same base image as the API server and mounts the same data, config, and model cache volumes.

### Nginx Proxy

Add the following to your nginx configuration to proxy MCP requests:

```nginx
location /mcp {
    proxy_pass http://mcp:8001/mcp;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}
```

## Authentication

The MCP server supports three authentication methods:

### 1. API Key

Clients can authenticate by passing an API key in the `X-API-Key` header. This matches either:
- The `API_SECRET_KEY` environment variable (master key) — takes effect immediately across all services
- An admin-generated key managed via the Admin → API Keys screen

> **Note:** Admin-generated keys are cached in-memory per service process with a 60-second TTL. After generating or revoking a key in the admin screen, allow up to 60 seconds before it takes effect in the MCP and A2A servers. The `API_SECRET_KEY` env var is always effective immediately.

### 2. OAuth 2.0 (for Claude and ChatGPT)

The MCP server implements OAuth 2.0 Authorization Server Metadata (RFC 8414) for browser-based login flows used by Claude Desktop and ChatGPT.

**Flow:**

1. Client discovers OAuth endpoints via `GET /mcp/.well-known/oauth-authorization-server`
2. Client redirects user to `/mcp/authorize` with PKCE parameters
3. User sees the Evidence Lab login page (email/password, Microsoft, or Google)
4. After login, Evidence Lab redirects back to `/mcp/complete` with the auth session
5. MCP server generates an authorization code and redirects to the client's callback
6. Client exchanges the code for an access token via `/mcp/token`
7. Client uses the access token as a Bearer token in subsequent MCP requests

**OAuth endpoints:**

| Endpoint | Description |
|----------|-------------|
| `GET /mcp/.well-known/oauth-authorization-server` | OAuth metadata discovery |
| `GET /mcp/authorize` | Authorization endpoint (redirects to login) |
| `GET /mcp/complete` | Post-login completion (generates auth code) |
| `POST /mcp/token` | Token exchange endpoint |
| `POST /mcp/register` | Dynamic client registration (RFC 7591) |

### 3. Bearer JWT

Clients can pass a JWT token in the `Authorization: Bearer <token>` header. The token is verified using the `AUTH_SECRET_KEY`.

## Tools

The MCP server exposes two tools, both read-only:

| Tool | Description | Rate Limit |
|------|-------------|------------|
| `search` | Hybrid semantic + keyword search across document chunks | 30/min |
| `get_document` | Retrieve full document metadata by ID | 30/min |

For synthesised research answers, use the [A2A Server](a2a-server.md) `research` skill.

Tool parameters, descriptions, and available data sources are driven by `config.json`. When data sources are added or removed, the MCP tool descriptions update automatically.

## Monitoring

### Audit Logging

All MCP tool calls are logged with:
- Tool name and input parameters
- Authentication method and user identity
- Response time and status
- Client IP address

Logs are written to the standard application log and can be viewed via `docker compose logs mcp`.

### Health Check

```bash
curl https://your-instance.example.com/mcp/health
```

Returns `{"status": "ok", "service": "mcp"}` when the server is running.

## Troubleshooting

### Connection Refused

Ensure the MCP container is running: `docker compose ps mcp`

If the container is not starting, check logs: `docker compose logs mcp`

### OAuth Login Not Working

- Verify `APP_BASE_URL` is set correctly (must be the externally-accessible URL)
- Ensure the nginx proxy is configured for `/mcp`
- Check that at least one OAuth provider (Microsoft or Google) is configured

### Rate Limiting

If users are hitting rate limits, adjust via environment variables:

```bash
RATE_LIMIT_MCP_SEARCH=60/minute
RATE_LIMIT_MCP_AI=20/minute
```

### Model Errors

If the A2A `research` skill returns model errors, verify the configured model combo is available. The default is "Azure Foundry" which requires Azure OpenAI credentials. Check that `AZURE_FOUNDRY_API_KEY` and `AZURE_FOUNDRY_ENDPOINT` are set. See [A2A Server](a2a-server.md#troubleshooting).
