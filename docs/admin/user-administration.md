## User Administration

Evidence Lab includes a full authentication and authorization system built on [fastapi-users](https://fastapi-users.github.io/fastapi-users/). This guide covers setup, authentication methods, user and group management, and the admin panel.

---

### Authentication Modes

Control authentication behavior with the `REACT_APP_USER_MODULE` environment variable in `.env`:

| Mode | Behavior |
|------|----------|
| `off` (default) | No authentication — everyone has full access |
| `on_passive` | Sign-in is available but optional; anonymous users can browse freely |
| `on_active` | All access requires login |

---

### Setting Up Authentication

#### 1. Email/Password Authentication

Email/password registration works out of the box once you enable the user module. Key environment variables:

```env
REACT_APP_USER_MODULE=on_active
FIRST_SUPERUSER_EMAIL=admin@example.com    # Auto-creates the first admin account
FIRST_SUPERUSER_PASSWORD=your-secure-password
```

**Password requirements:** minimum 8 characters, at least 1 letter and 1 digit. Passwords are hashed with bcrypt.

**Domain restriction:** Optionally limit who can register:
```env
AUTH_ALLOWED_EMAIL_DOMAINS=yourdomain.com,partner.org
```

#### 2. Setting Up Google OAuth

To enable "Sign in with Google":

1. Go to the [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create an **OAuth 2.0 Client ID** (Web application type)
3. Add the **Authorized redirect URI**:
   - Local development: `http://localhost:8000/auth/google/callback`
   - Production: `https://yourdomain.com/api/auth/google/callback`
4. Copy the Client ID and Secret into your `.env`:

```env
OAUTH_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
OAUTH_GOOGLE_CLIENT_SECRET=your-client-secret
```

Evidence Lab requests the `openid`, `email`, and `profile` scopes. If a user registers with email/password first and then signs in with Google using the same email, the accounts are automatically linked.

#### 3. Setting Up Microsoft / Azure OAuth

To enable "Sign in with Microsoft":

1. Go to the [Azure Portal App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps)
2. Register a new application
3. Under **Authentication**, add a **Web** redirect URI:
   - Local development: `http://localhost:8000/auth/microsoft/callback`
   - Production: `https://yourdomain.com/api/auth/microsoft/callback`
4. Under **Certificates & secrets**, create a new client secret
5. Copy the values into your `.env`:

```env
OAUTH_MICROSOFT_CLIENT_ID=your-application-client-id
OAUTH_MICROSOFT_CLIENT_SECRET=your-client-secret
OAUTH_MICROSOFT_TENANT_ID=common
```

The **tenant ID** controls who can sign in:
- `common` — any Microsoft account (personal + work/school)
- A specific tenant ID (e.g., `your-org-tenant-id`) — restricts sign-in to that organization only

Evidence Lab requests the `openid`, `email`, `profile`, and `User.Read` scopes.

#### 4. Setting Up Email (SMTP)

Evidence Lab sends two types of email: **account verification** (on registration) and **password reset**. Configure your SMTP server:

```env
SMTP_HOST=smtp.yourdomain.com
SMTP_PORT=587
SMTP_USER=noreply@yourdomain.com
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=noreply@evidencelab.ai
SMTP_USE_TLS=true
APP_BASE_URL=https://yourdomain.com    # Used in email links
```

If `SMTP_HOST` is left empty, emails are silently skipped (but logged to the container output so you can still see verification tokens during development).

**Token lifetimes** (optional, in seconds):
```env
AUTH_RESET_TOKEN_LIFETIME=86400      # Password reset: 24 hours (default)
AUTH_VERIFY_TOKEN_LIFETIME=604800    # Email verification: 7 days (default)
```

#### 5. Testing Emails with Mailpit

For local development, [Mailpit](https://mailpit.axllent.org/) provides a fake SMTP server with a web inbox — no real emails are sent.

**Step 1:** Start Mailpit (it uses a Docker Compose profile so it's not started by default):
```bash
docker compose --profile mail up -d mailpit
```

**Step 2:** Configure `.env` for Mailpit:
```env
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USE_TLS=false
# Leave SMTP_USER and SMTP_PASSWORD empty
```

**Step 3:** Restart the API to pick up the new settings:
```bash
docker compose up -d api
```

**Step 4:** Open the Mailpit inbox at **http://localhost:8025** — all verification and password-reset emails will appear here.

> **Quick testing shortcut:** Set `DISABLE_EMAIL_CONFIRMATION=true` in `.env` to auto-verify accounts on registration (skips the email step entirely). **Never use this in production.**

---

### Security Features

| Feature | Description | Configuration |
|---------|-------------|---------------|
| **Account lockout** | Locks accounts after repeated failed logins | `AUTH_MAX_LOGIN_ATTEMPTS=5`, `AUTH_LOCKOUT_DURATION=900` (15 min) |
| **Rate limiting** | Throttles login, registration, and reset endpoints per IP | Built-in, no configuration needed |
| **Audit logging** | Records all security events (login, logout, password changes) in an append-only log | Automatic |
| **CSRF protection** | Double-submit cookie pattern prevents cross-site request forgery | Automatic |
| **Cookie-based sessions** | httpOnly, secure, SameSite cookies — no tokens in localStorage | Automatic |

---

### Managing Users

Access the Admin Panel by clicking your avatar in the top right, then selecting **Admin**. The **Users** tab shows all registered users.

![Admin Users panel](/docs/images/admin/users-panel.png)

From the Users panel you can:

- **Search** for users by email or name
- **Create a new user** — click the "+" button to open the create modal. New users are auto-verified and added to the default group.
- **Toggle user flags** using the checkboxes in each row:
  - **Active** — enable or disable the account
  - **Verified** — manually verify or unverify
  - **Admin** — promote to or demote from superuser
- **Delete a user** — removes the account, group memberships, OAuth links, and anonymizes audit logs

---

### Managing Groups

The **Groups** tab lets you create and manage user groups. Groups control which datasets users can access and provide default search settings.

![Admin Groups panel](/docs/images/admin/groups-panel.png)

The panel has two sections:

**Left: Group list** — shows all groups with member count and dataset count. The **Default** group is marked with a badge and cannot be deleted.

**Right: Group detail** — select a group to see:

- **Group name and description** — editable
- **Dataset Access** — checkboxes for each configured datasource. Toggle which datasets this group can access.
- **Members** — table of current members. Add members from the dropdown picker, or remove existing members.

> New users are automatically added to the default group on registration.

---

### Group Settings

The **Group Settings** tab lets you configure default search behavior for each group. Users inherit these defaults when they log in, but can still override them in the UI.

![Admin Group Settings](/docs/images/admin/group-settings.png)

Select a group using the radio buttons at the top, then configure:

#### Search Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **Search Mode** (dense weight slider) | Balance between Semantic (1.0) and Keyword (0.0) search | 0.8 |
| **Keyword Boost Short Queries** | Auto-boost keyword weight for 1–2 word queries | On |
| **Semantic Highlighting** | Use AI to highlight relevant phrases in results | On |
| **Auto Min Score** | Automatically determine minimum relevance threshold | Off |
| **Rerank** | Use a cross-encoder model to rerank results | On |
| **Recency Boost** | Prioritize recently published reports | Off |
| **Recency Weight** | How strongly recency affects ranking (0.05–0.5) | 0.15 |
| **Recency Scale** | Decay period from 6 months to 5 years | 365 days |
| **Deduplicate** | Remove duplicate content found across reports | On |
| **Field Boost** | Boost specific metadata fields in ranking | On |
| **Field Boost Fields** | Which fields to boost (Country, Organization, etc.) with weights | Country: 1, Org: 0.5 |

#### Content Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **Min Chunk Size** | Filter out chunks smaller than this character count | 100 |
| **Section Types** | Which document sections to include in search results | 7 types selected |

#### Appearance

| Setting | Description |
|---------|-------------|
| **Greeting Message** | Custom text for the search placeholder on the landing page |

#### AI Summary

| Setting | Description |
|---------|-------------|
| **Summary Prompt** | Custom system prompt for AI summaries. If empty, uses the built-in default. |

Click **Save Settings** to apply, or **Reset to Defaults** to clear all group overrides.

---

### User Self-Service

Users have access to a **Profile** modal (click avatar → Profile) where they can:

- **Edit their name** (first name, last name)
- **View their group memberships** (read-only)
- **Delete their account** — requires typing "DELETE" to confirm. Permanently removes the account, group memberships, OAuth links, ratings, and activity logs.
