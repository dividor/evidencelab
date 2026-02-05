"""TOC parsing and selection helpers for tagger."""

import re
from typing import Any, Dict, List, Optional

from pipeline.processors.tagging.tagger_constants import SECTION_TYPES

TOC_LINE_PATTERN = re.compile(
    r"^(?P<indent>\s*)\[H(?P<level>\d+)\]\s*(?P<title>.*?)"
    r"(?:\s*\|\s*page\s*(?P<page>\d+)"
    r"(?:\s*\((?P<roman>[^)]+)\))?\s*(?P<fm>\[Front\])?)?\s*$",
    flags=re.IGNORECASE,
)


def normalize_title(title: str) -> str:
    """Normalize a TOC title for comparison."""
    return re.sub(r"\s+", " ", title.strip().lower())


def parse_toc(toc_text: str) -> List[Dict[str, Any]]:
    """
    Parse document["toc"] into structured entries.

    Output entry fields:
      - index: stable index in parsed TOC order (0..N-1)
      - title: cleaned title string
      - normalized_title: normalized title for matching
      - level: integer heading level
      - page: integer page number or None
      - original_line: original TOC line
      - indentation: indentation whitespace prefix (preserved for output formatting)
    """
    entries: List[Dict[str, Any]] = []

    if not toc_text:
        return entries

    for raw_line in toc_text.splitlines():
        original_line = raw_line.rstrip("\n")
        if not original_line.strip():
            continue

        # Keep original indentation for output, but also parse in a robust way.
        match = TOC_LINE_PATTERN.match(original_line.strip())
        if not match:
            # Not a recognized TOC entry; skip it to avoid poisoning classification.
            continue

        heading_level = int(match.group("level"))
        title_text = (match.group("title") or "").strip()
        page_text = match.group("page")
        roman_label = match.group("roman")
        fm_marker = match.group("fm")

        # Normalize dotted leaders inside title (optional; keeps meaning but reduces noise)
        title_text = re.sub(r"\.{2,}", " ", title_text).strip()

        page_number: Optional[int] = (
            int(page_text) if page_text and page_text.isdigit() else None
        )

        entry_index = len(entries)
        indentation = match.group("indent") or ""

        entries.append(
            {
                "index": entry_index,
                "title": title_text,
                "normalized_title": normalize_title(title_text),
                "level": heading_level,
                "page": page_number,
                "roman": roman_label.strip() if roman_label else None,
                "original_line": original_line,
                "indentation": indentation,
                "fm": bool(fm_marker),
            }
        )

    return entries


def build_normalized_title_to_indices(
    toc_entries: List[Dict[str, Any]]
) -> Dict[str, List[int]]:
    """Map normalized TOC titles to their indices."""
    mapping: Dict[str, List[int]] = {}
    for entry in toc_entries:
        normalized_title = entry["normalized_title"]
        mapping.setdefault(normalized_title, []).append(entry["index"])
    return mapping


def format_toc_line(entry: Dict[str, Any], label: str) -> str:
    """Format a TOC entry with a label and optional page."""
    indentation = entry.get("indentation", "")
    level = entry["level"]
    title = entry["title"]
    page = entry.get("page")
    roman = entry.get("roman")
    fm_marker = entry.get("fm")
    if page is None:
        return f"{indentation}[H{level}] {title} | {label}"
    roman_suffix = f" ({roman})" if roman else ""
    fm_suffix = " [Front]" if fm_marker else ""
    return (
        f"{indentation}[H{level}] {title} | {label} | page {page}"
        f"{roman_suffix}{fm_suffix}"
    )


def select_toc_entry_by_page(
    toc_entries: List[Dict[str, Any]], chunk_page_number: int
) -> Optional[Dict[str, Any]]:
    """
    Select the TOC entry that best matches a chunk page using page ranges:
    choose the entry with greatest page <= chunk_page_number.
    Ties on same page choose the later TOC index (more specific / later).
    """
    best_entry: Optional[Dict[str, Any]] = None
    for entry in toc_entries:
        entry_page = entry.get("page")
        if entry_page is None:
            continue
        if entry_page <= chunk_page_number:
            if best_entry is None:
                best_entry = entry
            else:
                best_page = best_entry.get("page")
                if best_page is None:
                    best_entry = entry
                elif entry_page > best_page:
                    best_entry = entry
                elif entry_page == best_page and entry["index"] > best_entry["index"]:
                    best_entry = entry
    return best_entry


def select_toc_entry_by_heading_match(
    toc_entries: List[Dict[str, Any]],
    normalized_title_to_indices: Dict[str, List[int]],
    labels_by_index: Dict[int, str],
    chunk_headings: List[str],
    chunk_page_number: Optional[int],
) -> Optional[int]:
    """
    Fallback selection when page selection is not possible.
    Match chunk headings against TOC titles. If multiple matches exist and chunk page is known,
    choose match with closest page <= chunk page; otherwise choose the last matching TOC index.
    """
    _ = labels_by_index
    if not chunk_headings:
        return None

    candidate_indices = _find_candidate_indices(
        chunk_headings, normalized_title_to_indices
    )
    if not candidate_indices:
        return None

    if chunk_page_number is not None:
        best_index = _best_index_by_page(
            toc_entries, candidate_indices, chunk_page_number
        )
        if best_index is not None:
            return best_index

    return max(candidate_indices)


def _find_candidate_indices(
    chunk_headings: List[str],
    normalized_title_to_indices: Dict[str, List[int]],
) -> List[int]:
    for heading in reversed(chunk_headings):
        normalized_heading = normalize_title(heading)
        matched_indices = normalized_title_to_indices.get(normalized_heading)
        if matched_indices:
            return list(matched_indices)
    return []


def _best_index_by_page(
    toc_entries: List[Dict[str, Any]],
    candidate_indices: List[int],
    chunk_page_number: int,
) -> Optional[int]:
    best_index: Optional[int] = None
    best_page: Optional[int] = None
    for index_value in candidate_indices:
        entry = _safe_entry(toc_entries, index_value)
        if not entry:
            continue
        entry_page = entry.get("page")
        if entry_page is None or entry_page > chunk_page_number:
            continue
        best_index, best_page = _pick_best_index(
            best_index, best_page, index_value, entry_page
        )
    return best_index


def _safe_entry(
    toc_entries: List[Dict[str, Any]], index_value: int
) -> Optional[Dict[str, Any]]:
    if 0 <= index_value < len(toc_entries):
        return toc_entries[index_value]
    return None


def _pick_best_index(
    best_index: Optional[int],
    best_page: Optional[int],
    index_value: int,
    entry_page: int,
) -> tuple[int, int]:
    if best_index is None or best_page is None:
        return index_value, entry_page
    if entry_page > best_page:
        return index_value, entry_page
    if entry_page == best_page and index_value > best_index:
        return index_value, entry_page
    return best_index, best_page


def ensure_label_is_valid(label: str) -> str:
    """Return label if valid, otherwise 'other'."""
    return label if label in SECTION_TYPES else "other"
