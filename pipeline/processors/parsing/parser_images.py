"""Image and table asset helpers for parsing."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def make_relative_path(path: str) -> str:
    """
    Convert absolute path to relative path starting with 'data/'.

    Finds '/data/' or 'data/' in the path and returns everything from there.
    """
    path_str = str(path).replace("\\", "/")

    data_mount_path = os.getenv("DATA_MOUNT_PATH")
    if data_mount_path:
        mount_str = os.path.abspath(data_mount_path).replace("\\", "/").rstrip("/")
        if path_str.startswith(f"{mount_str}/"):
            rel = path_str[len(mount_str) + 1 :]
            return f"data/{rel}"

    data_marker = "/data/"
    idx = path_str.find(data_marker)
    if idx != -1:
        return path_str[idx + 1 :]

    if path_str.startswith("./data/"):
        return path_str[2:]
    if path_str.startswith("data/"):
        return path_str

    return path_str


def fix_picture_captions(json_path: Path) -> None:
    """Post-process parsed JSON to fix picture captions."""
    try:
        with open(json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        pattern = _build_caption_pattern()
        pictures = data.get("pictures", [])
        texts = data.get("texts", [])
        text_by_ref = _build_text_by_ref(texts)

        modified = False
        for pic_idx, picture in enumerate(pictures):
            if _fix_picture_caption(picture, pic_idx, texts, text_by_ref, pattern):
                modified = True

        if modified:
            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            logger.info("  ✓ Fixed picture captions in JSON")

    except Exception as exc:
        logger.warning("  ⚠ Could not fix picture captions: %s", exc)


def save_table_images(_parser, document, output_folder: str) -> dict:
    """Save table images from parsed document."""
    tables_dir = Path(output_folder) / "tables"
    table_images: Dict[int, Dict[str, Any]] = {}
    table_idx = 0

    for item, _level in document.iterate_items():
        if type(item).__name__ != "TableItem":
            continue
        metadata = _save_table_image(item, tables_dir, table_idx)
        if metadata:
            table_images[table_idx] = metadata
        table_idx += 1

    _write_table_images_metadata(tables_dir, table_images)
    return table_images


def save_images_metadata(_parser, document, output_folder: str) -> dict:
    """Save metadata for picture items (figures, charts, etc.)."""
    images_dir = Path(output_folder) / "images"
    images_metadata: Dict[str, Any] = {}
    image_paths = _find_markdown_image_paths(output_folder)

    picture_idx = 0
    for item, _level in document.iterate_items():
        if type(item).__name__ != "PictureItem":
            continue
        metadata = _build_picture_metadata(item, picture_idx, image_paths)
        images_metadata[str(picture_idx)] = metadata
        picture_idx += 1

    _write_images_metadata(images_dir, images_metadata)
    return images_metadata


def _build_caption_pattern() -> re.Pattern:
    caption_patterns = [
        r"^GRAPH\s*\d",
        r"^FIGURE\s*\d",
        r"^TABLE\s*\d",
        r"^CHART\s*\d",
        r"^DIAGRAM\s*\d",
        r"^MAP\s*\d",
        r"^IMAGE\s*\d",
        r"^PHOTO\s*\d",
        r"^EXHIBIT\s*\d",
        r"^ILLUSTRATION\s*\d",
    ]
    return re.compile("|".join(caption_patterns), re.IGNORECASE)


def _build_text_by_ref(
    texts: list,
) -> Dict[str, tuple[int, Dict[str, Any]]]:
    text_by_ref: Dict[str, tuple[int, Dict[str, Any]]] = {}
    for i, text_item in enumerate(texts):
        ref = text_item.get("self_ref", f"#/texts/{i}")
        text_by_ref[ref] = (i, text_item)
    return text_by_ref


def _fix_picture_caption(
    picture: Dict[str, Any],
    pic_idx: int,
    texts: list,
    text_by_ref: Dict[str, tuple[int, Dict[str, Any]]],
    pattern: re.Pattern,
) -> bool:
    modified = False
    children = picture.get("children", [])
    for child_ref in children:
        ref = child_ref.get("$ref", "")
        if ref not in text_by_ref:
            continue
        text_idx, text_item = text_by_ref[ref]
        if _should_convert_to_caption(text_item, pattern):
            _promote_to_caption(texts, text_idx)
            _ensure_caption_ref(picture, ref)
            modified = True
            logger.debug(
                "  Fixed caption for picture %s: %s...",
                pic_idx,
                text_item.get("text", "")[:50],
            )
    return modified


def _should_convert_to_caption(text_item: Dict[str, Any], pattern: re.Pattern) -> bool:
    label = text_item.get("label", "")
    text_content = text_item.get("text", "")
    return label == "section_header" and bool(pattern.match(text_content))


def _promote_to_caption(texts: list, text_idx: int) -> None:
    texts[text_idx]["label"] = "caption"
    if "level" in texts[text_idx]:
        del texts[text_idx]["level"]


def _ensure_caption_ref(picture: Dict[str, Any], ref: str) -> None:
    caption_ref = {"$ref": ref}
    existing_captions = picture.get("captions", [])
    if caption_ref in existing_captions:
        return
    if "captions" not in picture:
        picture["captions"] = []
    picture["captions"].append(caption_ref)


def _save_table_image(
    item: Any, tables_dir: Path, table_idx: int
) -> Dict[str, Any] | None:
    if not (hasattr(item, "image") and item.image is not None):
        return None
    if not hasattr(item.image, "pil_image"):
        return None
    try:
        pil_image = item.image.pil_image
        tables_dir.mkdir(parents=True, exist_ok=True)
        page_num = _get_page_num(item)
        image_filename = f"table_{table_idx:03d}_page_{page_num}.png"
        image_path = tables_dir / image_filename
        pil_image.save(str(image_path), "PNG")
        return {
            "image_path": make_relative_path(str(image_path)),
            "page_num": page_num,
            "size": list(pil_image.size),
        }
    except Exception as exc:
        logger.debug("Failed to save table %s image: %s", table_idx, exc)
        return None


def _get_page_num(item: Any) -> int | str:
    if hasattr(item, "prov") and item.prov:
        for prov in item.prov:
            if hasattr(prov, "page_no"):
                return prov.page_no
    return "unknown"


def _write_table_images_metadata(
    tables_dir: Path, table_images: Dict[int, Dict[str, Any]]
) -> None:
    if not table_images:
        return
    metadata_path = tables_dir / "table_images.json"
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(table_images, handle, indent=2)


def _find_markdown_image_paths(output_folder: str) -> list[str]:
    markdown_path = next(Path(output_folder).glob("*.md"), None)
    if not markdown_path or not markdown_path.exists():
        return []
    with open(markdown_path, "r", encoding="utf-8") as handle:
        content = handle.read()
    return re.findall(r"!\[Image\]\((.*?\.(?:png|jpg|jpeg))\)", content, re.IGNORECASE)


def _build_picture_metadata(
    item: Any, picture_idx: int, image_paths: list[str]
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "index": picture_idx,
        "self_ref": getattr(item, "self_ref", None),
    }
    if picture_idx < len(image_paths):
        metadata["path"] = make_relative_path(image_paths[picture_idx])
    metadata.update(_extract_picture_prov(item))
    return metadata


def _extract_picture_prov(item: Any) -> Dict[str, Any]:
    if not (hasattr(item, "prov") and item.prov):
        return {}
    for prov in item.prov:
        metadata: Dict[str, Any] = {}
        if hasattr(prov, "page_no"):
            metadata["page"] = prov.page_no
        if hasattr(prov, "bbox") and prov.bbox:
            bbox = prov.bbox.as_tuple()
            metadata["bbox"] = list(bbox)
            page_height = 842
            position_from_top = page_height - bbox[3]
            metadata["position_hint"] = round(position_from_top / page_height, 3)
        return metadata
    return {}


def _write_images_metadata(images_dir: Path, images_metadata: Dict[str, Any]) -> None:
    if not images_metadata:
        return
    metadata_path = images_dir / "images_metadata.json"
    images_dir.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(images_metadata, handle, indent=2)
