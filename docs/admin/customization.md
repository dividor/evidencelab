# Customization & Branding

Rebrand Evidence Lab — colors, fonts, logo, favicon, header and footer — with a
folder of static assets. No forking, no diff files, no `make`.

> **Customization is optional.** Out of the box Evidence Lab runs on built-in
> defaults; with nothing set, the build is byte-identical to stock. Reach for
> this only to restyle a deployment.

> Datasources, models, and search settings are **not** branding — those live in
> the top-level `config.json`, which a deployment edits directly. This page is
> only about the visual skin.

## Set it up (Docker-native)

Point an env var at a folder of branding assets, then build. The folder can live
anywhere on disk; unset means stock Evidence Lab.

```bash
export CUSTOMIZE_ASSETS=/path/to/your-branding   # optional
docker compose -f docker-compose.prod.yml up -d --build
```

Compose pulls that folder in as a build context (`additional_contexts`), and the
build copies whatever it finds over the defaults. Anything you omit keeps the
stock value — so a folder with just `theme.css` only changes colors/fonts.

## What the folder can contain (all optional)

```
theme.css        # colors, fonts, header & footer — plain CSS
logo.png         # header logo (served at /logo.png)
favicon.ico
og-image.png     # social share image
manifest.json    # PWA name / theme color
fonts/*.woff2    # self-hosted webfonts (referenced by theme.css)
```

## `theme.css` — colors, fonts, header, footer

`theme.css` is loaded **after** the app's stylesheet, so anything in it wins. It
overrides the app's design tokens, and you can add any plain CSS to restyle the
header or footer.

### Colors

Override the `--brand-*` tokens; every `--color-*` derives from them via `var()`,
so the rest of the palette follows automatically:

```css
:root {
  --brand-primary: #2A93FC;
  --brand-primary-dark: #037CF5;   /* hover/active + app title */
  --brand-accent: #1F6EBC;
  --brand-text-primary: #404040;
}
```

### Fonts

Self-host woff2 files in `fonts/`, declare the faces (reference them
**relatively**, `./fonts/<file>`), and point the `--font-*` tokens at them. The
build fingerprints fonts to same-origin `/static/media/` — **CSP-safe**, no
external Google-Fonts request:

```css
@font-face {
  font-family: 'Lato'; font-weight: 400; font-display: swap;
  src: url('./fonts/Lato-400.woff2') format('woff2');
}
:root {
  --font-body: 'Lato', sans-serif;
  --font-heading: 'Lato', sans-serif;
}
```

### Header & footer

Restyle them with plain CSS — the header is the top bar (`.app-title` for the
title), the footer is `#static-footer` (the Privacy/Terms block):

```css
#static-footer { background: #f5f7fa; padding: 1.25rem; }
.app-title { letter-spacing: 0.01em; }
```

## How it works

- `docker-compose.prod.yml` declares a `customize` build context defaulting to
  the stock `./customize` folder, overridden by `CUSTOMIZE_ASSETS`.
- `ui/frontend/Dockerfile.prod` does `COPY --from=customize` and runs
  [`scripts/custom/apply_branding.sh`](../../scripts/custom/apply_branding.sh),
  which copies any present asset over the default and bundles fonts.
- Branding assets (logo/favicon/manifest) are served `Cache-Control: no-cache`,
  so a re-brand appears on the next load instead of being cached for a year.

Stock builds (no `CUSTOMIZE_ASSETS`) copy nothing and are byte-identical to plain
Evidence Lab.
