"""Image-related chunking helpers."""

import re
from typing import Any, Dict, List, Set


def add_images_to_chunk_elements(
    chunk_elements: List[Dict[str, Any]],
    elements: List[Dict[str, Any]],
    images_by_page: Dict[int, List[Dict[str, Any]]],
    page_nums: Set[int],
) -> None:
    """Add images to chunk_elements with bbox overlap filtering."""
    text_bbox_ranges_by_page = calculate_text_bbox_ranges(elements)

    has_caption_keywords = any(
        elem.get("text", "").strip().lower().startswith(("figure", "table", "diagram"))
        for elem in elements
    )

    for page in page_nums:
        if page in images_by_page:
            for img in images_by_page[page]:
                img_bbox = img.get("bbox")

                if page in text_bbox_ranges_by_page and img_bbox:
                    include_image = should_include_image(
                        img_bbox, text_bbox_ranges_by_page[page], has_caption_keywords
                    )

                    if include_image:
                        chunk_elements.append(
                            {
                                "element_type": "image",
                                "path": img.get("path"),
                                "bbox": img.get("bbox"),
                                "page": img.get("page"),
                                "position_hint": img.get("position_hint"),
                            }
                        )
                else:
                    chunk_elements.append(
                        {
                            "element_type": "image",
                            "path": img.get("path"),
                            "bbox": img.get("bbox"),
                            "page": img.get("page"),
                            "position_hint": img.get("position_hint"),
                        }
                    )


def calculate_text_bbox_ranges(
    elements: List[Dict[str, Any]]
) -> Dict[int, Dict[str, float]]:
    """Calculate Y-coordinate bbox ranges from text elements by page."""
    text_bbox_ranges_by_page: Dict[int, Dict[str, float]] = {}

    for elem in elements:
        if elem.get("bbox") and elem.get("page"):
            page = elem["page"]
            bbox = elem["bbox"]

            if page not in text_bbox_ranges_by_page:
                text_bbox_ranges_by_page[page] = {
                    "min_y": float("inf"),
                    "max_y": float("-inf"),
                }

            text_bbox_ranges_by_page[page]["min_y"] = min(
                text_bbox_ranges_by_page[page]["min_y"], bbox[1]
            )
            text_bbox_ranges_by_page[page]["max_y"] = max(
                text_bbox_ranges_by_page[page]["max_y"], bbox[3]
            )

    return text_bbox_ranges_by_page


def should_include_image(
    img_bbox: List[float], text_range: Dict[str, float], has_caption_keywords: bool
) -> bool:
    """Determine if image should be included based on bbox overlap with text."""
    img_min_y = img_bbox[1]
    img_max_y = img_bbox[3]

    strict_overlaps = not (
        img_max_y < text_range["min_y"] or img_min_y > text_range["max_y"]
    )

    if strict_overlaps:
        return True

    if has_caption_keywords:
        tolerance = 250
        text_min_with_tolerance = text_range["min_y"] - tolerance
        text_max_with_tolerance = text_range["max_y"] + tolerance
        overlaps_with_tolerance = not (
            img_max_y < text_min_with_tolerance or img_min_y > text_max_with_tolerance
        )
        return overlaps_with_tolerance

    return False


def filter_images_before_text(
    chunk_elements: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Filter out images that appear before the first text element."""
    if not chunk_elements:
        return chunk_elements

    first_text_idx = None
    first_text_is_caption = False

    for idx, elem in enumerate(chunk_elements):
        if elem.get("element_type") == "text":
            first_text_idx = idx
            label = elem.get("label", "")
            text = elem.get("text", "")

            first_text_is_caption = (
                label == "caption"
                or text.strip().lower().startswith(("figure", "table", "diagram"))
            )
            break

    if first_text_idx is not None and not first_text_is_caption:
        return [
            elem
            for idx, elem in enumerate(chunk_elements)
            if idx >= first_text_idx
            or elem.get("element_type") == "text"
            or elem.get("element_type") == "table"
        ]

    return chunk_elements


def filter_table_metadata_text(
    chunk_elements: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Filter out table extraction metadata text that shouldn't be displayed."""
    filtered = []
    for elem in chunk_elements:
        if elem.get("element_type") == "text":
            text = elem.get("text", "").strip()

            if len(text) < 100:
                metadata_patterns = [
                    r"best\s+match.*score.*\d+",
                    r"\[sheet:.*\]",
                    r"sheet:.*score",
                    r"^prov[_\s]",
                    r"^otsl[_\s]",
                ]

                is_metadata = any(
                    re.search(pattern, text.lower()) for pattern in metadata_patterns
                )

                if is_metadata:
                    continue

        filtered.append(elem)

    return filtered


def extract_chunk_images(
    elements: List[Dict[str, Any]],
    images_by_page: Dict[int, List[Dict[str, Any]]],
    page_nums: Set[int],
) -> List[Dict[str, Any]]:
    """Extract images list for backward compatibility."""
    chunk_images = []

    text_bbox_ranges_by_page = calculate_text_bbox_ranges(elements)
    has_caption_keywords = any(
        elem.get("text", "").strip().lower().startswith(("figure", "table", "diagram"))
        for elem in elements
    )

    for page in page_nums:
        if page in images_by_page:
            for img in images_by_page[page]:
                img_bbox = img.get("bbox")

                if page in text_bbox_ranges_by_page and img_bbox:
                    include_image = should_include_image(
                        img_bbox, text_bbox_ranges_by_page[page], has_caption_keywords
                    )

                    if include_image:
                        chunk_images.append(img)
                else:
                    chunk_images.append(img)

    return chunk_images
