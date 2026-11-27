# MCP Server Administration

The MCP server runs as a separate Docker service that exposes Evidence Lab's search tools via the [Model Context Protocol](https://modelcontextprotocol.io/). The same service also hosts the [A2A Server](a2a-server.md) for agent-to-agent research tasks.

> **Tools:** `search`, `get_document`, and Heatmapper. Research synthesis is handled by the [A2A Server](a2a-server.md).

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
| `MCP_PUBLIC_URL` | `APP_BASE_URL` followed by `/mcp` | Exact public connector URL for OAuth and the Heatmapper sandbox |
| `OAUTH_CALLBACK_BASE_URL` | `http://localhost:8000` | Base URL for OAuth callbacks |
| `RATE_LIMIT_MCP_SEARCH` | `30/minute` | Shared allowance for search, document retrieval, and Heatmapper, per user or API key |
| `RATE_LIMIT_MCP_AI` | `10/minute` | Rate limit for ask_assistant tool, per caller |

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

The key built into the web interface (`REACT_APP_API_KEY`) is never accepted, even when it is also `API_SECRET_KEY`: anyone who loads the site can read it. Give the web interface its own key so the master key stays private, or use an admin-generated key. The MCP service reads `REACT_APP_API_KEY` from `.env` to know which key that is; on a deployment that sets environment variables per service, give the MCP service `REACT_APP_API_KEY` as well.

> **Note:** Admin-generated keys are cached in-memory per service process with a 60-second TTL. After generating or revoking a key in the admin screen, allow up to 60 seconds before it takes effect in the MCP and A2A servers. The `API_SECRET_KEY` env var is always effective immediately.

### 2. OAuth 2.0 (for Claude and ChatGPT)

The MCP server implements OAuth 2.0 Authorization Server Metadata (RFC 8414) for browser-based login flows used by Claude Desktop and ChatGPT.

**Flow:**

1. Client discovers OAuth endpoints via `GET /mcp/.well-known/oauth-authorization-server`
2. Client opens `/mcp/authorize` with PKCE parameters in the user's browser, which sets a short-lived cookie tying the request to that browser
3. User sees the Evidence Lab login page (email/password, Microsoft, or Google)
4. After login, the browser goes to `/mcp/complete`, which asks **Allow this app?**, naming the client and where it will be sent
5. When the user allows it, the MCP server generates an authorization code and redirects to the client's callback; when they deny it, the callback gets `error=access_denied`
6. Client exchanges the code for an access token via `/mcp/token`
7. Client uses the access token as a Bearer token in subsequent MCP requests

`/mcp/complete` only works in the browser that opened `/mcp/authorize`, for a person signed in to Evidence Lab there. A link to a request started anywhere else is refused, so nobody can send you a link that connects their app to your account. The access token works for MCP and A2A only; the web app does not accept it.

**OAuth endpoints:**

| Endpoint | Description |
|----------|-------------|
| `GET /mcp/.well-known/oauth-authorization-server` | OAuth metadata discovery |
| `GET /mcp/authorize` | Authorization endpoint (redirects to login) |
| `GET /mcp/complete` | After login: the consent page |
| `POST /mcp/complete` | Records the allow/deny answer and redirects to the client |
| `POST /mcp/token` | Token exchange endpoint |
| `POST /mcp/register` | Dynamic client registration (RFC 7591) |

Registrations are kept in the MCP server's memory, so a restart forgets them. A registration request may be at most 16 KB, with at most 10 `redirect_uris` of at most 2,048 characters each and a `client_name` of at most 200; anything larger is refused. At most 1,000 registrations are kept: a new one replaces the oldest that never got a token.

### 3. Bearer JWT

Clients can pass a JWT token in the `Authorization: Bearer <token>` header. The token is verified using the `AUTH_SECRET_KEY`. MCP accepts both an Evidence Lab sign-in token and an MCP access token; the web app accepts only sign-in tokens.

## Tools

The MCP server exposes read-only tools:

| Tool | Description | Rate Limit |
|------|-------------|------------|
| `search` | Hybrid semantic + keyword search across document chunks | 1 unit from the shared allowance |
| `get_document` | Retrieve full document metadata by ID | 1 unit from the shared allowance |
| `heatmap` | Compare counts in a grid with up to 24 cells | 1 unit to plan, plus 1 per cell |
| `heatmap_cell` | List documents from a selected grid cell | 1 unit per page |

For synthesised research answers, use the [A2A Server](a2a-server.md) `research` skill.

Tool parameters, descriptions, and available data sources are driven by `config.json`. When data sources are added or removed, the MCP tool descriptions update automatically.

## Heatmapper in an MCP Apps host

Set `APP_BASE_URL` to the public Evidence Lab web address. Set
`MCP_PUBLIC_URL` to the exact public HTTPS address you will enter in Claude,
including any path prefix and `/mcp`. A different trailing slash changes the
sandbox origin. Use [the custom connector steps](../overview/mcp.md#connecting-claude)
to sign in. Inline rendering and clicking a cell use the connector's existing
authentication. The HTML has no external scripts or API calls.

For local testing through a Claude Desktop standard-input/output (stdio)
bridge, use the local HTTP address for `MCP_PUBLIC_URL`. Claude gives the
local app its sandbox origin. If the bridge connects to an HTTPS deployment,
strip `_meta.ui.domain` from its UI resource responses before forwarding them
to Claude Desktop.

When the user module is enabled, signed-in MCP users must have access to the
requested data source through Group Settings for Search and Heatmapper.
Server and managed API keys retain access to the configured data sources.
Each heatmap and each selected-cell call adds an entry to the MCP audit log.
Hosts that support app-only tool visibility show `heatmap_cell` to the app.

The Heatmapper uses Evidence Lab’s logo, colors, and typefaces. Docker Compose reads
the same [branding folder](customization.md) as the web build when
`CUSTOMIZE_ASSETS` is set. For a separate MCP service, mount that folder
read-only and set `MCP_BRANDING_DIR` to its path inside the service. The view
uses the name from `manifest.json`, embeds `logo.png` as a PNG up to 512 KiB,
and reads the `--brand-primary`, `--brand-primary-light`, and
`--brand-accent-dark` colors from `theme.css` as three- or six-digit hex
values. The Heatmapper bundles Evidence Lab's Open Sans and Poppins fonts.
When the theme sets `--font-body` or `--font-heading`, the Heatmapper can
use matching normal WOFF2 faces from its `fonts/` folder. It supports font
weights 400, 600, and 700, with a 64 KiB limit per font file. The browser
loads the font bytes from the HTML without requesting a font URL.

The Python Docker image includes the HTML. For host development, build it
from the checkout with Node 22 or later before starting the MCP server.

```sh
npm ci --prefix mcp_server/resources/heatmap --legacy-peer-deps --ignore-scripts
npm run --prefix mcp_server/resources/heatmap build
```

Read the tool and resource metadata using an existing server or admin-managed
API key from your shell environment.

```sh
rpc() {
  curl --silent --show-error --fail-with-body "$MCP_PUBLIC_URL" \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -H "X-API-Key: $MCP_API_KEY" --data "$1"
}

rpc '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | jq '.result.tools[] | select(.name == "heatmap") | {name, _meta}'

rpc '{"jsonrpc":"2.0","id":2,"method":"resources/read","params":{"uri":"ui://evidencelab/heatmap.html"}}' \
  | jq '.result.contents[] | {uri, mimeType, _meta, htmlCharacters: (.text | length)}'
```

The tool points to `ui://evidencelab/heatmap.html` and the resource returns
`text/html;profile=mcp-app`. With the default allowance of 30 units per minute,
a full heatmap uses 25 units. A deployment with a smaller allowance also has
a smaller grid limit.

## Monitoring

### Audit Logging

Every MCP tool call and A2A task execution is recorded in the `mcp_audit_log` database table and is visible in the **Admin → MCP / A2A** tab.

Each entry records:

| Field | Description |
|-------|-------------|
| **Protocol** | `mcp` (tool call) or `a2a` (task execution) |
| **Tool / Method** | e.g. `search`, `get_document`, `tasks/send` |
| **Auth** | Authentication method used (`api_key`, `oauth`, `jwt`) |
| **User** | Authenticated user ID if available |
| **IP** | Client IP address |
| **Duration** | Time to complete the call |
| **Status** | `ok` or `error` |
| **Summary** | Brief output summary or error message |

The tab has dropdowns to filter by **Protocol** (All / MCP / A2A) and **Status** (All / OK / Error), and paginates 50 entries at a time newest-first.

> **Note:** Audit entries are written asynchronously. They require a working database connection from the `mcp` container. If entries are missing, check `docker compose logs mcp` for `Failed to create asyncpg pool` warnings and verify `POSTGRES_PASSWORD` is set correctly.

Log output from the container is also available via:

```bash
docker compose logs mcp
```

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

If the A2A `research` skill returns model errors, verify the configured model combo is available. The default is "Azure Foundry" which requires Azure OpenAI credentials. Check that `AZURE_FOUNDRY_KEY` and `AZURE_FOUNDRY_ENDPOINT` are set. See [A2A Server](a2a-server.md#troubleshooting).
