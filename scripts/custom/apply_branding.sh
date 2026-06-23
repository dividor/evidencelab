#!/bin/sh
# Apply the deployment branding overlay into the frontend build tree.
#
# Copies any present custom asset over its base counterpart. A missing file
# means "no override for that asset" — the intended no-op for an uncustomized
# build, not a silent fallback hiding a bug. The committed skeleton under
# ./custom keeps this a no-op for vanilla builds. See
# docs/deployment/customization.md.
#
# Usage: apply_branding.sh <overlay-dir> <public-dir> <src-dir>
set -eu

OVERLAY="$1"
PUBLIC="$2"
SRC="$3"

copy_if_present() {
    if [ -f "$1" ]; then
        cp "$1" "$2"
        echo "branding: applied $1 -> $2"
    fi
}

# Resolved config (rendered by scripts/custom/merge_config.py / `make customize`).
copy_if_present "$OVERLAY/config.resolved.json" "$SRC/config.json"

# Static branding assets.
copy_if_present "$OVERLAY/branding/logo.png"      "$PUBLIC/logo.png"
copy_if_present "$OVERLAY/branding/favicon.ico"   "$PUBLIC/favicon.ico"
copy_if_present "$OVERLAY/branding/og-image.png"  "$PUBLIC/og-image.png"
copy_if_present "$OVERLAY/branding/manifest.json" "$PUBLIC/manifest.json"

# Theme: CSS variable overrides, imported after App.css via src/custom-theme.css.
copy_if_present "$OVERLAY/branding/theme.css"     "$SRC/custom-theme.css"

# Self-hosted branding fonts. They go under src/ so the bundler fingerprints
# them to same-origin /static/media/ (CSP-safe: font-src 'self'). theme.css
# @font-face rules reference them relatively, e.g. url('./fonts/<file>').
if [ -d "$OVERLAY/branding/fonts" ]; then
    mkdir -p "$SRC/fonts"
    cp -R "$OVERLAY/branding/fonts/." "$SRC/fonts/"
    echo "branding: applied fonts -> $SRC/fonts/"
fi
