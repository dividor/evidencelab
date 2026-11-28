"""Read the local font faces used by a deployment's Heatmapper."""

import base64
import json
import re
from pathlib import Path

_FONT_FACES = re.compile(r"@font-face\s*\{([^{}]+)\}")
_FONT_FAMILY = re.compile(r"""["']?([a-zA-Z0-9][a-zA-Z0-9 _-]{0,59})["']?""")
_LOCAL_SOURCE = re.compile(
    r"""url\(\s*["']?(?:\./)?fonts/([a-zA-Z0-9_.-]+\.woff2)["']?\s*\)"""
    r"""(?:\s*format\(\s*["']?woff2["']?\s*\))?"""
)
_FONT_TOKENS = ("--font-body", "--font-heading")
_FONT_WEIGHTS = {"400", "600", "700"}
_MAX_FONT_BYTES = 64 * 1024


def _family(value: str) -> str | None:
    match = _FONT_FAMILY.fullmatch(value.split(",", 1)[0].strip())
    return match[1] if match else None


def _read_face(fonts: Path, filename: str) -> str:
    font = (fonts / filename).resolve()
    if not font.is_relative_to(fonts):
        raise ValueError("Heatmapper fonts must be inside the branding fonts folder.")
    with font.open("rb") as file:
        data = file.read(_MAX_FONT_BYTES + 1)
    if not data.startswith(b"wOF2") or len(data) > _MAX_FONT_BYTES:
        raise ValueError("Each Heatmapper font must be WOFF2 and at most 64 KiB.")
    return base64.b64encode(data).decode("ascii")


def _face_declarations(block: str) -> dict[str, str]:
    return dict(
        (key.strip(), value.strip())
        for key, separator, value in (item.partition(":") for item in block.split(";"))
        if separator
    )


def _font_faces(css: str, families: set[str], fonts: Path) -> list[dict[str, str]]:
    faces = {}
    for block in _FONT_FACES.findall(css):
        face = _face_declarations(block)
        family = _family(face.get("font-family", ""))
        weight = face.get("font-weight", "400")
        if family is None or family not in families or weight not in _FONT_WEIGHTS:
            continue
        if face.get("font-style", "normal") != "normal":
            continue
        source = _LOCAL_SOURCE.fullmatch(face.get("src", ""))
        if source:
            faces[family, weight] = {
                "family": family,
                "weight": weight,
                "data": _read_face(fonts, source[1]),
            }
    return list(faces.values())


def heatmap_fonts(css: str, directory: Path) -> tuple[str, str]:
    """Use the local, normal-weight faces selected by the web theme."""
    tokens = {}
    for token in _FONT_TOKENS:
        values = re.findall(rf"(?:^|[{{;])\s*{token}\s*:\s*([^;}}]+)", css)
        family = _family(values[-1]) if values else None
        if family:
            tokens[token] = family
    faces = _font_faces(css, set(tokens.values()), directory / "fonts")
    loaded = {face["family"] for face in faces}
    declarations = "".join(
        f'{token}: "{family}";' for token, family in tokens.items() if family in loaded
    )
    return declarations, json.dumps(faces, separators=(",", ":"))
