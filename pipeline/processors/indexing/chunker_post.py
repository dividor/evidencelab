"""
Post-processing helpers for chunk metadata.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from docling_core.types.doc import DoclingDocument

logger = logging.getLogger(__name__)


def post_process_chunks(
    doc: DoclingDocument, chunks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Post-process chunks to enhance metadata with cross-chunk information.
    """
    footnote_numbers = _build_footnote_registry(doc)
    if footnote_numbers:
        logger.info(
            "Found %s footnote/endnote numbers in document", len(footnote_numbers)
        )

    footnote_elements_map = _build_footnote_elements_map(chunks)
    _annotate_inline_references(chunks, footnote_numbers)

    for chunk in chunks:
        chunk_elements = chunk.get("chunk_elements", [])
        referenced_footnotes = _collect_referenced_footnotes(chunk_elements)
        filtered_elements, present_footnotes, removed_footnotes = (
            _filter_chunk_elements(chunk_elements, referenced_footnotes)
        )
        added_footnotes = _add_missing_footnotes(
            filtered_elements,
            referenced_footnotes - present_footnotes,
            footnote_elements_map,
        )
        _sort_chunk_elements(filtered_elements)
        chunk["chunk_elements"] = filtered_elements
        chunk["text"] = _build_chunk_text(filtered_elements)
        chunk["text"] = _inject_hierarchy_prefix(
            chunk["text"], chunk.get("headings", [])
        )
        _log_footnote_changes(removed_footnotes, added_footnotes)

    return chunks


def _annotate_inline_references(
    chunks: List[Dict[str, Any]], footnote_numbers: set
) -> None:
    for chunk in chunks:
        for elem in chunk.get("chunk_elements", []):
            if elem.get("is_reference"):
                continue
            if elem.get("element_type") == "text" and elem.get("text"):
                inline_refs = _detect_inline_references(elem["text"], footnote_numbers)
                if inline_refs:
                    elem["inline_references"] = inline_refs


def _collect_referenced_footnotes(chunk_elements: List[Dict[str, Any]]) -> set:
    referenced = set()
    for elem in chunk_elements:
        for ref in elem.get("inline_references", []):
            referenced.add(ref["number"])
    return referenced


def _filter_chunk_elements(
    chunk_elements: List[Dict[str, Any]], referenced_footnotes: set
) -> Tuple[List[Dict[str, Any]], set, int]:
    present_footnotes = set()
    filtered_elements = []
    removed_footnotes = 0
    for elem in chunk_elements:
        if elem.get("is_reference"):
            footnote_num = _extract_footnote_number(elem)
            if footnote_num is None:
                filtered_elements.append(elem)
                continue
            if footnote_num in referenced_footnotes:
                filtered_elements.append(elem)
                present_footnotes.add(footnote_num)
            else:
                removed_footnotes += 1
        else:
            filtered_elements.append(elem)
    return filtered_elements, present_footnotes, removed_footnotes


def _extract_footnote_number(elem: Dict[str, Any]) -> Optional[int]:
    if elem.get("label") != "footnote":
        return None
    text = elem.get("text", "")
    match = re.search(
        r"^(?:\[\^|\[|\^|<sup>)*(\d{1,3})(?:\]|</sup>|:)*\s",
        text.strip(),
    )
    return int(match.group(1)) if match else None


def _add_missing_footnotes(
    filtered_elements: List[Dict[str, Any]],
    missing_footnotes: set,
    footnote_elements_map: Dict[int, Dict[str, Any]],
) -> int:
    added_footnotes = 0
    for footnote_num in missing_footnotes:
        if footnote_num in footnote_elements_map:
            filtered_elements.append(footnote_elements_map[footnote_num])
            added_footnotes += 1
    return added_footnotes


def _sort_chunk_elements(filtered_elements: List[Dict[str, Any]]) -> None:
    filtered_elements.sort(key=lambda x: (x.get("page", 0), x.get("position_hint", 0)))


def _build_chunk_text(filtered_elements: List[Dict[str, Any]]) -> str:
    text_parts = []
    for elem in filtered_elements:
        if elem.get("element_type") == "text" and elem.get("text"):
            text_parts.append(elem["text"])
        elif elem.get("element_type") == "table":
            text_parts.extend(_build_table_text(elem))
    return "\n\n".join(text_parts)


def _build_table_text(elem: Dict[str, Any]) -> List[str]:
    table_text_parts = []
    rows = elem.get("rows", [])
    for row in rows:
        row_texts = []
        for cell in row:
            cell_text = cell.get("text", "").strip()
            if cell_text:
                row_texts.append(cell_text)
        if row_texts:
            table_text_parts.append(" ".join(row_texts))
    if table_text_parts:
        return ["\n".join(table_text_parts)]
    return []


def _inject_hierarchy_prefix(text: str, headings: Any) -> str:
    if not headings or not isinstance(headings, list):
        return text
    clean_headings = [
        str(h).replace("<", "").replace(">", "").strip() for h in headings
    ]
    if not clean_headings:
        return text
    selected_headings = clean_headings[-3:]
    hierarchy_prefix = "-- " + " > ".join(selected_headings) + " --"
    return f"{hierarchy_prefix}\n\n{text}"


def _log_footnote_changes(removed_footnotes: int, added_footnotes: int) -> None:
    if removed_footnotes > 0 or added_footnotes > 0:
        logger.debug(
            "Chunk footnote management: removed %s unreferenced, "
            "added %s missing referenced footnotes",
            removed_footnotes,
            added_footnotes,
        )


def _build_footnote_elements_map(
    chunks: List[Dict[str, Any]]
) -> Dict[int, Dict[str, Any]]:
    footnote_map = {}
    for chunk in chunks:
        chunk_elements = chunk.get("chunk_elements", [])
        for elem in chunk_elements:
            if elem.get("is_reference"):
                text = elem.get("text", "")
                match = re.match(
                    r"^(?:\[\^|\[|\^|<sup>)*(\d{1,3})(?:\]|</sup>|:)*\s",
                    text.strip(),
                )
                if match:
                    footnote_num = int(match.group(1))
                    if footnote_num not in footnote_map:
                        footnote_map[footnote_num] = elem
    return footnote_map


def _build_footnote_registry(doc: DoclingDocument) -> Set[int]:
    footnote_numbers = set()
    for item, _ in doc.iterate_items():
        item_type = type(item).__name__
        if item_type in ["TextItem", "DocItem"]:
            label = getattr(item, "label", "")
            if label in ["footnote", "endnote"]:
                text = getattr(item, "text", "")
                if text:
                    match = re.match(
                        r"^(?:\[\^|\[|\^|<sup>)*(\d{1,3})(?:\]|</sup>|:)*\s",
                        text.strip(),
                    )
                    if match:
                        footnote_numbers.add(int(match.group(1)))
    return footnote_numbers


def _detect_inline_references(
    text: str, footnote_numbers: Set[int]
) -> List[Dict[str, Any]]:
    patterns = [
        (r"\.\s+(\d{1,3})\s+", "period_space"),
        (r"^(\d{1,3})\s+", "start_of_text"),
        (r",\s+(\d{1,3})\s+", "comma_space"),
        (r"\.\s+(\d{1,3})\n", "period_newline"),
        (r"\^(\d{1,3})", "geometric_caret"),
        (r"\[\^(\d{1,3})\]", "bracket_caret"),
        (r"<sup>(\d{1,3})</sup>", "html_tag"),
    ]

    inline_refs: List[Dict[str, Any]] = []

    for pattern, pattern_name in patterns:
        for match in re.finditer(pattern, text):
            ref_num = int(match.group(1))
            if ref_num in footnote_numbers:
                if not any(
                    ref["number"] == ref_num and ref["position"] == match.start(1)
                    for ref in inline_refs
                ):
                    inline_refs.append(
                        {
                            "number": ref_num,
                            "position": match.start(1),
                            "pattern": pattern_name,
                        }
                    )

    return inline_refs
