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
stock value — a folder with just `theme.css` only changes colors/fonts.

## What the folder can contain (all optional)

```
theme.css        # colors, fonts, header & footer styling — plain CSS
logo.png         # header logo (served at /logo.png)
favicon.ico
og-image.png     # social share image
manifest.json    # PWA name / theme color
fonts/*.woff2    # self-hosted webfonts (referenced by theme.css)
footer.md        # markdown that replaces the default footer
```

## `theme.css` — colors, fonts, header, footer

`theme.css` is loaded **after** the app's stylesheet, so anything in it wins. It
overrides the app's design tokens, and you can add any plain CSS to restyle the
header or footer.

- **Colors** — override the `--brand-*` tokens; every `--color-*` derives from
  them via `var()`, so the palette follows automatically.
- **Fonts** — declare `@font-face`s (reference `fonts/` files **relatively**) and
  point `--font-*` at them. Fonts are bundled to same-origin `/static/media/` —
  CSP-safe, no external Google-Fonts request.
- **Header / footer** — plain CSS: the header is the top bar (`.app-title` for
  the title), the footer is `.app-footer`.

## `footer.md` — replace the footer

Drop a `footer.md` in the folder and it **fully replaces** the default footer
(About · Privacy · Terms · GitHub …) with your rendered markdown. Omit it to keep
the default.

```markdown
© 2026 World Food Programme · [Privacy](/privacy) · [Terms](/terms) ·
[wfp.org](https://www.wfp.org)
```

## Full example

A complete branding folder overriding every supported option:

```
my-branding/
├── theme.css
├── logo.png
├── favicon.ico
├── og-image.png
├── manifest.json
├── footer.md
└── fonts/
    ├── Brand-400.woff2
    └── Brand-700.woff2
```

`theme.css` covering all the tokens:

```css
/* --- Fonts --------------------------------------------------------------- */
@font-face {
  font-family: 'Brand'; font-weight: 400; font-display: swap;
  src: url('./fonts/Brand-400.woff2') format('woff2');
}
@font-face {
  font-family: 'Brand'; font-weight: 700; font-display: swap;
  src: url('./fonts/Brand-700.woff2') format('woff2');
}

:root {
  /* Typography */
  --font-body: 'Brand', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-heading: 'Brand', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'SF Mono', Menlo, Monaco, Consolas, monospace;

  /* Primary palette (everything else derives from these) */
  --brand-primary: #2A93FC;
  --brand-primary-dark: #037CF5;        /* hover/active + app title */
  --brand-primary-light: #85C1FD;
  --brand-accent: #1F6EBC;
  --brand-accent-dark: #155A99;

  /* Text + surfaces */
  --brand-text-primary: #404040;
  --brand-text-secondary: #5E5E5E;
  --brand-text-tertiary: #8C8C8C;
  --brand-border: #E8E8E8;
  --brand-border-light: #F0F0F0;
  --brand-background: #FAFBFC;
  --brand-surface: #FFFFFF;

  /* Status */
  --brand-success: #00A878;
  --brand-warning: #FFC759;
  --brand-error: #FF5252;
}

/* Header / footer styling (optional) */
.app-title { letter-spacing: 0.01em; }
.app-footer { background: #F5F7FA; }
```

## How it works

- `docker-compose.prod.yml` declares a `customize` build context defaulting to
  the stock `./customize` folder, overridden by `CUSTOMIZE_ASSETS`.
- `ui/frontend/Dockerfile.prod` does `COPY --from=customize` and runs
  [`scripts/custom/apply_branding.sh`](../../scripts/custom/apply_branding.sh),
  which copies any present asset over the default and bundles fonts.
- The `AppFooter` component renders `footer.md` (served at `/footer.md`) when
  present, otherwise the default footer.
- Branding assets (logo/favicon/manifest) are served `Cache-Control: no-cache`,
  so a re-brand appears on the next load instead of being cached for a year.

Stock builds (no `CUSTOMIZE_ASSETS`) copy nothing and are byte-identical to plain
Evidence Lab.
