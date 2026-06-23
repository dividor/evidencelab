#!/bin/sh
# Apply optional branding assets from the `customize` build context into the
# frontend build tree. A missing file means "keep the default" — the intended
# no-op for a stock build (not a silent fallback). See
# docs/admin/customization.md.
#
# Usage: apply_branding.sh <customize-dir> <public-dir> <src-dir>
set -eu

CUSTOMIZE="$1"
PUBLIC="$2"
SRC="$3"

copy_if_present() {
    if [ -f "$1" ]; then
        cp "$1" "$2"
        echo "branding: applied $1 -> $2"
    fi
}

# Static branding assets.
copy_if_present "$CUSTOMIZE/logo.png"      "$PUBLIC/logo.png"
copy_if_present "$CUSTOMIZE/favicon.ico"   "$PUBLIC/favicon.ico"
copy_if_present "$CUSTOMIZE/og-image.png"  "$PUBLIC/og-image.png"
copy_if_present "$CUSTOMIZE/manifest.json" "$PUBLIC/manifest.json"

# Theme: colors, fonts, header/footer — plain CSS. Imported after App.css via
# src/custom-theme.css so the overrides win the cascade.
copy_if_present "$CUSTOMIZE/theme.css"     "$SRC/custom-theme.css"

# Self-hosted fonts. They go under src/ so the bundler fingerprints them to
# same-origin /static/media/ (CSP-safe: font-src 'self'). theme.css @font-face
# rules reference them relatively, e.g. url('./fonts/<file>').
if [ -d "$CUSTOMIZE/fonts" ]; then
    mkdir -p "$SRC/fonts"
    cp -R "$CUSTOMIZE/fonts/." "$SRC/fonts/"
    echo "branding: applied fonts -> $SRC/fonts/"
fi
