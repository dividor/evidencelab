"""Validate the Heatmapper's local-only font declarations."""

import base64
import json

import pytest

from mcp_server.resources.heatmap_fonts import heatmap_fonts

pytestmark = pytest.mark.unit


def theme(source: str, name: str = "Lato", style: str = "normal") -> str:
    return (
        f":root {{ --font-body: '{name}', sans-serif; --font-heading: '{name}'; }}"
        "@font-face {"
        f"font-family: '{name}'; font-style: {style}; font-weight: 700;"
        f"src: {source};"
        "}"
    )


def font_file(directory):
    fonts = directory / "fonts"
    fonts.mkdir()
    return fonts / "Lato.woff2"


def test_heatmap_fonts_reuses_a_local_face_for_both_tokens(tmp_path):
    path = font_file(tmp_path)
    data = b"wOF2" + bytes(12)
    path.write_bytes(data)

    tokens, faces = heatmap_fonts(
        theme("url('./fonts/Lato.woff2') format('woff2')"), tmp_path
    )

    assert tokens == '--font-body: "Lato";--font-heading: "Lato";'
    assert json.loads(faces) == [
        {"data": base64.b64encode(data).decode(), "family": "Lato", "weight": "700"}
    ]


@pytest.mark.parametrize(
    ("source", "family", "style"),
    [
        ("url('https://example.org/Lato.woff2')", "Lato", "normal"),
        ("url('./fonts/../Lato.woff2')", "Lato", "normal"),
        ("url('./fonts/Lato.woff2')", "</script>", "normal"),
        ("url('./fonts/Lato.woff2')", "Lato", "italic"),
    ],
)
def test_heatmap_fonts_does_not_forward_unsupported_declarations(
    source, family, style, tmp_path
):
    assert heatmap_fonts(theme(source, family, style), tmp_path) == ("", "[]")


def test_heatmap_fonts_rejects_a_font_symlink_outside_the_folder(tmp_path):
    outside = tmp_path / "outside.woff2"
    outside.write_bytes(b"wOF2")
    path = font_file(tmp_path)
    path.symlink_to(outside)

    with pytest.raises(ValueError, match="inside the branding fonts folder"):
        heatmap_fonts(theme("url('./fonts/Lato.woff2')"), tmp_path)


@pytest.mark.parametrize("data", [b"invalid", b"wOF2" + bytes(64 * 1024)])
def test_heatmap_fonts_rejects_invalid_or_oversized_fonts(tmp_path, data):
    font_file(tmp_path).write_bytes(data)

    with pytest.raises(ValueError, match="WOFF2 and at most 64 KiB"):
        heatmap_fonts(theme("url('./fonts/Lato.woff2')"), tmp_path)
