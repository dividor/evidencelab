"""Render branding from the deployment's web assets into the Heatmapper HTML."""

import base64
import json
import os
import re
from html import escape
from pathlib import Path

_BRAND_COLORS = ("--brand-primary", "--brand-primary-light", "--brand-accent-dark")
_COLOR_DECLARATION = re.compile(
    rf"(?:^|(?<=[{{;]))\s*({'|'.join(_BRAND_COLORS)})\s*:\s*([^;}}]*)"
)
_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
_TEMPLATE_MARKER = re.compile(r"\{\{(BRAND_NAME|BRAND_LOGO|BRAND_COLORS)\}\}")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_LOGO_BYTES = 512 * 1024


def _site_name(directory: Path | None) -> str:
    manifest = directory / "manifest.json" if directory else None
    if manifest is None or not manifest.exists():
        return "Evidence Lab"
    settings = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("The branding manifest must be an object.")
    name = settings.get("name", "Evidence Lab")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("The branding manifest needs a nonempty name.")
    return name.strip()


def _brand_colors(directory: Path | None) -> str:
    theme = directory / "theme.css" if directory else None
    if theme is None or not theme.exists():
        return ""
    css = re.sub(r"/\*.*?\*/", "", theme.read_text(encoding="utf-8"), flags=re.DOTALL)
    colors = {}
    for token, value in _COLOR_DECLARATION.findall(css):
        color = value.strip()
        if not _HEX_COLOR.fullmatch(color):
            raise ValueError(
                "Heatmapper theme colors must be three- or six-digit hex values."
            )
        colors[token] = color
    return "; ".join(f"{token}: {color}" for token, color in colors.items())


def _logo_url(directory: Path | None, stock_logo: Path) -> str:
    override = directory / "logo.png" if directory else None
    logo = override if override is not None and override.exists() else stock_logo
    with logo.open("rb") as file:
        data = file.read(_MAX_LOGO_BYTES + 1)
    if len(data) > _MAX_LOGO_BYTES or not data.startswith(_PNG_SIGNATURE):
        raise ValueError("The Heatmapper logo must be a PNG of at most 512 KiB.")
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def apply_heatmap_branding(html: str, stock_logo: Path) -> str:
    configured = os.getenv("MCP_BRANDING_DIR")
    directory = Path(configured) if configured else None
    if directory is not None and not directory.is_dir():
        raise ValueError("The Heatmapper branding folder is unavailable.")
    replacements = {
        "BRAND_NAME": escape(_site_name(directory), quote=True),
        "BRAND_LOGO": _logo_url(directory, stock_logo),
        "BRAND_COLORS": _brand_colors(directory),
    }
    return _TEMPLATE_MARKER.sub(lambda match: replacements[match[1]], html)
