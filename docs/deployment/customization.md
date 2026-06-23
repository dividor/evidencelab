# Deployment Customization & Branding

Evidence Lab supports **per-deployment customization** — config deltas, branding
(colors, logo, favicon), and deploy files (Caddyfile, compose override, `.env`) —
without forking the repo or leaving untracked files lying around.

All customization lives in a single **git-ignored overlay directory**, `custom/`,
which is populated from a separate repo (for example `wfp-evidencelab-custom`).
The build and runtime layer that overlay on top of the base; the tracked source
tree is never modified.

## Why an overlay

- **Clean working tree** — everything customized lives under one git-ignored
  directory, so `git status` stays clean on a deployment host.
- **No drift** — `config.json` and colors are applied as *deltas*, so a
  deployment automatically inherits base improvements instead of pinning a stale
  whole-file copy.
- **Separation** — the base repo owns the *mechanism*; the customization repo is
  pure *content* (data only, no scripts).

## How it is wired

Each customization is applied where it is actually consumed:

| Asset | When | How |
|-------|------|-----|
| `config.json` (frontend) | build | deep-merged from `config.overlay.json`, bundled into the UI |
| `config.json` (backend) | runtime | resolved file mounted at `/app/config.json` (no API rebuild) |
| Colors | build | `branding/theme.css` redefines the `--brand-*` tokens from `App.css`, imported after it as `src/custom-theme.css` so it wins the cascade |
| Fonts | build | `branding/theme.css` redefines `--font-*` tokens; self-hosted woff2 in `branding/fonts/` are bundled to same-origin `/static/media/` |
| Logo / favicon / OG / manifest | build | copied over `ui/frontend/public/*` |
| `nginx.conf` | build | overridden only if `deploy/nginx.conf` is present (rare — the base is a superset) |
| `Caddyfile` | runtime | bind-mounted from `custom/deploy/Caddyfile` |
| compose override | runtime | `-f custom/deploy/docker-compose.override.yml` |
| `.env` | runtime + build args | `--env-file custom/env/.env` |

```
base repo                custom repo (synced into ./custom)        result
─────────                ──────────────────────────────────       ──────
config.json        ─┐
                    ├─► scripts/custom/merge_config.py ─► custom/config.resolved.json
config.overlay.json ┘                                      ├─ bundled into UI (build)
                                                           └─ mounted into API (runtime)

public/* + branding/{logo,favicon,…} ─► public/* (build)        last write wins
App.css + branding/theme.css         ─► src/custom-theme.css (after App.css)

deploy/Caddyfile / docker-compose.override.yml / env/.env ─► layered at runtime
```

With no overlay applied, the committed skeleton under `custom/` is inert and the
build is byte-identical to an uncustomized Evidence Lab.

## Using it

On a deployment host:

```bash
# One-time: clone your customization repo somewhere
git clone git@github.com:<org>/<your>-evidencelab-custom.git /opt/evidencelab-custom
cp /opt/evidencelab-custom/env/.env.example /opt/evidencelab-custom/env/.env   # then fill in

# Sync the overlay into ./custom and bring up the stack
make prod-up CUSTOM=/opt/evidencelab-custom
```

`make customize CUSTOM=…` rsyncs the customization repo into `custom/` and renders
`custom/config.resolved.json`. `make prod-build` / `make prod-up` re-render the
config and build/run the production stack with the overlay applied.

## Customization repo structure

The customization repo is **content only** — no scripts. The merge logic and
build steps live in the base repo.

```
your-evidencelab-custom/
├── VERSION                          # base version this overlay targets (e.g. "base: v1.6.0")
├── README.md
├── .gitignore                       # ignores env/.env and config.resolved.json
│
├── config.overlay.json             # DELTAS ONLY — deep-merged onto base config.json
│
├── branding/
│   ├── theme.css                    # redefines :root { --brand-* / --font-* } tokens
│   ├── fonts/                       # optional self-hosted woff2 (referenced by theme.css)
│   ├── logo.png                     # served at /logo.png
│   ├── favicon.ico
│   ├── og-image.png                 # optional (1200×627 social card)
│   └── manifest.json                # optional (PWA theme_color/background_color)
│
├── deploy/
│   ├── docker-compose.override.yml  # only genuine infra deltas (mounts, mem, ports)
│   ├── Caddyfile                    # this deployment's reverse-proxy config
│   └── nginx.conf                   # OMIT unless you truly diverge from base nginx
│
└── env/
    └── .env.example                 # documents deployment-specific vars (real .env not committed)
```

### `config.overlay.json` merge rules

The overlay holds only your diffs. They are deep-merged onto the base
`config.json` ([`scripts/custom/merge_config.py`](../../scripts/custom/merge_config.py)):

- **objects** → recursively merged (overlay keys add or override)
- **scalars** → replaced
- **arrays** → replaced wholesale (never concatenated)
- a key whose value is `null` → **deleted** from the base
- an object containing `"$replace": true` → that whole subtree is **replaced**
  instead of merged (use when you want an exact set — e.g. only your datasources)

Example — keep only your datasource and bump one `application` value, inheriting
everything else from base:

```json
{
  "application": { "assistant": { "max_search_results": 30 } },
  "datasources": {
    "$replace": true,
    "WFP Evaluation Reports": { "data_subdir": "wfp", "field_mapping": { } }
  }
}
```

Unknown top-level keys are rejected (the schema is fixed), so a typo fails loud
rather than silently baking a key nothing reads.

### `branding/theme.css`

Override only the raw `--brand-*` tokens; every `--color-*` token derives from
them via `var()`, so the rest of the palette cascades automatically:

```css
:root {
  --brand-primary: #2A93FC;
  --brand-primary-dark: #037CF5;
  --brand-accent: #1F6EBC;
  /* …leave a token out and it keeps the base value */
}
```

### Fonts (`branding/fonts/` + `--font-*` tokens)

Typography is tokenized the same way as colors. The base defines `--font-body`,
`--font-heading`, and `--font-mono` in `App.css :root`; every `font-family`
declaration resolves through them. To rebrand the typeface:

1. Drop self-hostable font files (woff2) in `branding/fonts/`. At build time
   `apply_branding.sh` copies them under `src/fonts/`, so the bundler
   fingerprints them to same-origin `/static/media/` — **CSP-safe**
   (`font-src 'self'`); no external Google-Fonts request, no CSP change.
2. In `branding/theme.css`, declare the faces (reference files **relatively**,
   `./fonts/<file>`) and point the tokens at them:

```css
@font-face {
  font-family: 'Lato'; font-weight: 400; font-display: swap;
  src: url('./fonts/Lato-400.woff2') format('woff2');
}
:root {
  --font-body: 'Lato', -apple-system, sans-serif;
  --font-heading: 'Lato', -apple-system, sans-serif;
}
```

## Adding a new customizable asset

1. If it is consumed at **build** time, copy it in
   [`scripts/custom/apply_branding.sh`](../../scripts/custom/apply_branding.sh)
   (frontend) or the relevant Dockerfile stage.
2. If it is consumed at **runtime**, reference it from
   `custom/deploy/docker-compose.override.yml`.
3. Keep whole-file overrides to a minimum — prefer mergeable deltas so
   deployments keep inheriting base updates.
