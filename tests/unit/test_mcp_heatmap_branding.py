"""Exercise stock and deployment branding for the MCP Apps resource."""

import base64
import shutil
from pathlib import Path

import pytest

from mcp_server.resources.heatmap import load_heatmap_html

pytestmark = pytest.mark.unit

STOCK_LOGO = Path(__file__).parents[2] / "ui" / "frontend" / "public" / "logo.png"


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    directory = tmp_path / "mcp-assets"
    directory.mkdir()
    (directory / "heatmap.html").write_text(
        "<title>{{BRAND_NAME}}</title><style>:root { {{BRAND_COLORS}} }</style>"
        '<img src="{{BRAND_LOGO}}"><a>Open in {{BRAND_NAME}}</a>',
        encoding="utf-8",
    )
    shutil.copyfile(STOCK_LOGO, directory / "logo.png")
    monkeypatch.setenv("MCP_APP_ASSET_DIR", str(directory))
    monkeypatch.delenv("MCP_BRANDING_DIR", raising=False)
    return directory


def test_heatmap_branding_without_an_overlay_uses_the_stock_identity(packaged):
    html = load_heatmap_html()
    assert "<title>Evidence Lab</title>" in html
    assert "Open in Evidence Lab" in html
    assert base64.b64encode((packaged / "logo.png").read_bytes()).decode() in html


def test_heatmap_branding_with_overlay_escapes_name_and_embeds_assets(
    packaged, tmp_path, monkeypatch
):
    branding = tmp_path / "branding"
    branding.mkdir()
    monkeypatch.setenv("MCP_BRANDING_DIR", str(branding))
    logo = STOCK_LOGO.read_bytes() + b"custom-logo"
    (branding / "logo.png").write_bytes(logo)
    (branding / "manifest.json").write_text(
        '{"name": "Research & Evaluation <Lab> {{BRAND_LOGO}}"}', encoding="utf-8"
    )
    (branding / "theme.css").write_text(
        "/* :root { --brand-primary: red; } */"
        ":root { --brand-primary: #2a93fc; --brand-primary-light: #abc;"
        " --brand-accent-dark: #155A99; }"
        '@font-face { src: url("https://example.org/font.woff2"); }',
        encoding="utf-8",
    )

    html = load_heatmap_html()

    assert "Open in Research &amp; Evaluation &lt;Lab&gt; {{BRAND_LOGO}}" in html
    assert base64.b64encode(logo).decode() in html
    assert "--brand-primary: #2a93fc" in html
    assert "--brand-primary-light: #abc" in html
    assert "--brand-accent-dark: #155A99" in html
    assert "example.org" not in html


@pytest.mark.parametrize(
    ("asset", "content"),
    [
        ("theme.css", b":root { --brand-primary: </style><script> }"),
        ("theme.css", b":root { --brand-accent-dark: url(https://example.org/x); }"),
        ("manifest.json", b'{"name": 1}'),
        ("manifest.json", b'["name"]'),
        ("logo.png", b"<svg></svg>"),
    ],
)
def test_heatmap_branding_with_invalid_assets_returns_a_public_error(
    packaged, tmp_path, monkeypatch, asset, content
):
    monkeypatch.setenv("MCP_BRANDING_DIR", str(tmp_path))
    (tmp_path / asset).write_bytes(content)

    with pytest.raises(ValueError, match="The Heatmapper branding is invalid") as error:
        load_heatmap_html()

    assert str(tmp_path) not in str(error.value)


def test_heatmap_branding_of_missing_overlay_returns_a_public_error(
    packaged, tmp_path, monkeypatch
):
    monkeypatch.setenv("MCP_BRANDING_DIR", str(tmp_path / "missing"))

    with pytest.raises(ValueError, match="The Heatmapper branding is invalid"):
        load_heatmap_html()
