# `customize/` — default (stock) branding folder

This is the **default** target of the `customize` build context. It is empty,
so a stock build is plain Evidence Lab.

To rebrand, you do **not** edit the repo — point an env var at your own folder:

```bash
export CUSTOMIZE_ASSETS=/path/to/your-branding   # optional
docker compose -f docker-compose.prod.yml up -d --build
```

Your folder may contain any of (all optional):

```
theme.css        # colors, fonts, header & footer — plain CSS (--brand-*/--font-* + rules)
logo.png  favicon.ico  og-image.png  manifest.json
fonts/*.woff2
```

The build copies whatever is present over the defaults; anything you omit keeps
the stock value. See docs/admin/customization.md.
