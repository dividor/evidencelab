"""
Helpers for building chunker maps and indices.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from docling_core.types.doc import DoclingDocument, ListItem

logger = logging.getLogger(__name__)


def build_text_elements_map(
    doc: DoclingDocument, page_height: int
) -> Tuple[Dict[int, List[Dict[str, Any]]], Dict[str, str]]:
    """
    Collect ALL text elements from document with their page positions.
    Also builds a map of corrected text (e.g. lists with markers).
    """
    text_elements_by_page: Dict[int, List[Dict[str, Any]]] = {}
    fixed_text_map: Dict[str, str] = {}

    for item, _ in doc.iterate_items():
        if not _is_text_item(item):
            continue
        item_text = _resolve_text_item_text(item)
        if not item_text:
            continue
        element = _build_text_element(item, item_text, page_height)
        if element:
            _add_text_element(text_elements_by_page, element)
        _register_fixed_text(item, item_text, fixed_text_map)

    _log_text_elements_summary(text_elements_by_page)
    return text_elements_by_page, fixed_text_map


def build_table_index_map(
    doc: DoclingDocument, page_height: int
) -> Dict[str, Dict[str, Any]]:
    """
    Build table index mapping from document with bbox and position info.
    """
    table_index_map: Dict[str, Dict[str, Any]] = {}
    table_idx = 0

    for item, _ in doc.iterate_items():
        if not _is_table_item(item):
            continue
        table_ref = getattr(item, "self_ref", None)
        if table_ref:
            page, bbox, position_hint = _extract_table_prov_info(item, page_height)
            table_index_map[table_ref] = {
                "idx": table_idx,
                "bbox": bbox,
                "page": page,
                "position_hint": position_hint,
            }
        table_idx += 1

    return table_index_map


def _is_text_item(item: Any) -> bool:
    return type(item).__name__ in {
        "TextItem",
        "DocItem",
        "ListItem",
        "SectionHeaderItem",
    }


def _resolve_text_item_text(item: Any) -> str:
    if not (hasattr(item, "text") and item.text):
        return ""
    item_text = item.text
    if isinstance(item, ListItem) and getattr(item, "marker", None):
        clean_marker = item.marker.strip()
        if clean_marker and not item_text.strip().startswith(clean_marker):
            item_text = f"{item.marker} {item_text}"
            item.text = item_text
    return item_text


def _build_text_element(
    item: Any, item_text: str, page_height: int
) -> Optional[Dict[str, Any]]:
    prov = _get_first_prov(item, page_height)
    if not prov:
        return None
    page, bbox, position_hint = prov
    return {
        "text": item_text,
        "label": getattr(item, "label", "text"),
        "page": page,
        "bbox": bbox,
        "position_hint": position_hint,
        "self_ref": getattr(item, "self_ref", None),
    }


def _get_first_prov(
    item: Any, page_height: int
) -> Optional[Tuple[int, List[float], float]]:
    if not (hasattr(item, "prov") and item.prov):
        return None
    for prov in item.prov:
        if hasattr(prov, "page_no") and hasattr(prov, "bbox") and prov.bbox:
            page = prov.page_no
            bbox = list(prov.bbox.as_tuple())
            position_from_top = page_height - bbox[3]
            position_hint = round(position_from_top / page_height, 3)
            return page, bbox, position_hint
    return None


def _add_text_element(
    text_elements_by_page: Dict[int, List[Dict[str, Any]]], element: Dict[str, Any]
) -> None:
    page = element["page"]
    text_elements_by_page.setdefault(page, []).append(element)


def _register_fixed_text(
    item: Any, item_text: str, fixed_text_map: Dict[str, str]
) -> None:
    if hasattr(item, "self_ref") and item.self_ref:
        fixed_text_map[item.self_ref] = item_text


def _log_text_elements_summary(
    text_elements_by_page: Dict[int, List[Dict[str, Any]]]
) -> None:
    total = sum(len(values) for values in text_elements_by_page.values())
    logger.info(
        "Collected %s text elements across %s pages",
        total,
        len(text_elements_by_page),
    )


def _is_table_item(item: Any) -> bool:
    return type(item).__name__ == "TableItem"


def _extract_table_prov_info(
    item: Any, page_height: int
) -> Tuple[Optional[int], Optional[List[float]], Optional[float]]:
    if not (hasattr(item, "prov") and item.prov):
        return None, None, None
    for prov in item.prov:
        page = prov.page_no if hasattr(prov, "page_no") else None
        bbox = None
        position_hint = None
        if hasattr(prov, "bbox") and prov.bbox:
            bbox = list(prov.bbox.as_tuple())
            position_from_top = page_height - bbox[3]
            position_hint = round(position_from_top / page_height, 3)
        return page, bbox, position_hint
    return None, None, None
