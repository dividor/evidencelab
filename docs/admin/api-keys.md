## API

Evidence Lab provides a REST API for programmatic access to search, documents, and AI features. All API endpoints require authentication via an API key.

---

### API Documentation

Interactive API documentation is available via Swagger UI:

- **Local development**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Production**: `https://your-domain/api/docs`

The Swagger UI lets you explore all available endpoints, view request/response schemas, and test API calls directly from the browser. Click the **Authorize** button and enter your API key to authenticate.

---

### API Key Setup

#### Global API Key (Environment Variable)

Set a global key via the `API_SECRET_KEY` environment variable in `.env`:

```env
API_SECRET_KEY=your-secret-key-here
```

Generate a secure key:

```bash
openssl rand -hex 32
```

If `API_SECRET_KEY` is not set, the API starts with a warning and all unauthenticated requests are rejected.

#### Admin-Generated API Key

Administrators can generate an API key from the admin panel:

1. Open the **Admin** panel and select the **API Keys** tab.
2. Click **Generate** to create a new key.
3. The full key is displayed once — click **Copy** to copy it to your clipboard.
4. The key cannot be retrieved after leaving the page.

To regenerate a key, click **Regenerate**. This revokes the current key and creates a new one. Any applications using the old key will immediately lose access.

---

### Using the API

Include your API key in the `X-API-Key` header with every request:

```bash
curl -H "X-API-Key: your-key-here" https://your-domain/api/search?q=climate+change
```

#### Example: Search

```bash
curl -H "X-API-Key: your-key-here" \
  "https://your-domain/api/search?q=food+security&data_source=uneg&limit=10"
```

#### Example: Get Document

```bash
curl -H "X-API-Key: your-key-here" \
  "https://your-domain/api/document/43a156c7-afb5-5409-b3dc-c3e2c697d54a"
```

---

### Security Details

| Aspect | Implementation |
|--------|---------------|
| Key format | `el_` prefix + 32 bytes of `secrets.token_urlsafe` |
| Storage | SHA-256 hash only — plaintext is never stored |
| Lookup | In-memory cache of active hashes, invalidated on create/revoke |
| Access control | Superuser-only (admin panel) |
| Audit logging | Key creation and revocation events are logged |
| Cookie auth | Logged-in UI users authenticate via session cookies — no API key needed for browser use |

---

### API Key Management Endpoints

All endpoints require superuser authentication via session cookie.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api-keys/` | List all keys (prefix, creator, timestamps) |
| `POST` | `/api-keys/` | Generate a new key (returns full key once) |
| `DELETE` | `/api-keys/{key_id}` | Revoke a key |
