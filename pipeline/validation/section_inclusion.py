"""Section-inclusion validation.

Checks that every section inside a document's human-set main-body page range is
tagged with a section type that Search *includes* by default. A body section
tagged with an excluded type (e.g. ``annexes``) silently disappears from default
search results, so surfacing it lets an editor fix the classification.

Inputs come from a document row as returned by ``PostgresClient.fetch_docs`` /
``fetch_all_docs``:

* body page range -> ``src_doc_raw_metadata[INTRO_RANGE_FIELD]``, e.g. ``"(11, 62)"``
* section tags    -> ``sys_data["sys_toc_classified"]`` (the "Contents" tab tags)

This module holds only pure logic (no DB, no I/O) so it can be reused by the
backend service, the evaluation script, and unit tests alike.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Mirrors DEFAULT_SECTION_TYPES in ui/frontend/src/utils/searchUrl.ts — the
# section types that Search includes by default. Everything else is excluded.
DEFAULT_INCLUDED_SECTION_TYPES: Tuple[str, ...] = (
    "executive_summary",
    "context",
    "methodology",
    "findings",
    "conclusions",
    "recommendations",
    "other",
)

# Source-metadata field holding the human-set body page range, e.g. "(11, 62)".
INTRO_RANGE_FIELD = (
    "Introduction - before beginning of Annexes (start_page_number, end_page_number)"
)

# Matches classified-TOC lines, e.g.:
#   "[H1] 1. Introduction | introduction | page 11"
#   "[H2] Table des Matieres | front_matter | page 3 (i) [Front]"
# The trailing bracket marker ([Front], [FM], ...) and the roman-numeral page
# alias are both optional.
_TOC_CLASSIFIED_PATTERN = re.compile(
    r"^\s*\[H(?P<level>\d+)\]\s*(?P<title>.*?)\s*\|\s*(?P<label>[^|]+?)"
    r"(?:\s*\|\s*page\s*(?P<page>\d+)(?:\s*\([^)]+\))?)?"
    r"(?:\s*\[[^\]]*\])?\s*$",
    flags=re.IGNORECASE,
)

# One parsed classified-TOC entry: {"title": str, "label": str, "page": int|None}.
Section = Dict[str, Any]


def _parse_page_value(value: Any) -> Optional[int]:
    """Coerce a single page value (int/float/numeric-string) to int."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_page_range(raw_value: Any) -> Tuple[Optional[int], Optional[int]]:
    """Parse the body page range from the shapes it can take.

    In practice the stored value is a string like ``"(11, 62)"``, but tuples,
    lists, dicts and bare ints are handled too. Returns ``(start, end)``; either
    element may be ``None`` if it could not be determined.
    """
    if raw_value is None:
        return None, None

    if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
        return _parse_page_value(raw_value[0]), _parse_page_value(raw_value[1])

    if isinstance(raw_value, dict):
        start = raw_value.get("start_page_number", raw_value.get("start"))
        end = raw_value.get("end_page_number", raw_value.get("end"))
        return _parse_page_value(start), _parse_page_value(end)

    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        page = _parse_page_value(raw_value)
        return page, page

    if isinstance(raw_value, str):
        numbers = [int(val) for val in re.findall(r"\d+", raw_value)]
        if len(numbers) >= 2:
            return numbers[0], numbers[1]
        if len(numbers) == 1:
            return numbers[0], numbers[0]

    return None, None


def parse_toc_classified(toc_text: str) -> List[Section]:
    """Parse classified-TOC text into ``{title, label, page}`` entries."""
    if not toc_text:
        return []

    entries: List[Section] = []
    for raw_line in toc_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _TOC_CLASSIFIED_PATTERN.match(line)
        if not match:
            continue
        page_text = match.group("page")
        entries.append(
            {
                "title": (match.group("title") or "").strip(),
                "label": (match.group("label") or "").strip().lower(),
                "page": int(page_text) if page_text and page_text.isdigit() else None,
            }
        )
    return entries


def sections_in_range(
    entries: Iterable[Section], start_page: int, end_page: int
) -> List[Section]:
    """Return entries whose page falls within ``[start_page, end_page]``."""
    return [
        entry
        for entry in entries
        if entry.get("page") is not None and start_page <= entry["page"] <= end_page
    ]


def find_excluded_sections(
    entries: Iterable[Section],
    start_page: int,
    end_page: int,
    included: Iterable[str] = DEFAULT_INCLUDED_SECTION_TYPES,
) -> List[Section]:
    """Return in-range entries whose section type is excluded from Search by default.

    A section is a violation when its label is not in ``included`` — that content
    lives in the main body but would be filtered out of default search results.
    """
    included_set = set(included)
    return [
        entry
        for entry in sections_in_range(entries, start_page, end_page)
        if entry.get("label") not in included_set
    ]


def get_document_title(doc: Dict[str, Any]) -> str:
    """Best-effort document title from a doc row."""
    raw = doc.get("src_doc_raw_metadata") or {}
    return (
        doc.get("map_title")
        or doc.get("title")
        or raw.get("Title evaluation")
        or raw.get("title")
        or "Unknown"
    )


def get_intro_range_field(doc: Dict[str, Any]) -> Any:
    """Read the human-set body page range from a doc row."""
    raw = doc.get("src_doc_raw_metadata") or {}
    return raw.get(INTRO_RANGE_FIELD)


def get_toc_classified(doc: Dict[str, Any]) -> str:
    """Read the classified TOC text from a doc row (sys_data or top level)."""
    sys_data = doc.get("sys_data") or {}
    return sys_data.get("sys_toc_classified") or doc.get("sys_toc_classified") or ""


def _verdict(reasons: List[str], excluded: List[Section]) -> str:
    if reasons:
        return "skipped"
    return "fail" if excluded else "pass"


def evaluate_document(
    doc: Dict[str, Any],
    included: Iterable[str] = DEFAULT_INCLUDED_SECTION_TYPES,
) -> Dict[str, Any]:
    """Evaluate one document row and return a structured validation result.

    Result keys: ``status`` (pass/fail/skipped), ``range_start``, ``range_end``,
    ``sections_in_range``, ``num_excluded``, ``excluded_section_types`` (sorted
    unique labels), ``excluded_sections`` (list of ``{title, label, page}``), and
    ``reasons`` (why a document was skipped, if any).
    """
    start_page, end_page = parse_page_range(get_intro_range_field(doc))
    entries = parse_toc_classified(get_toc_classified(doc))

    reasons: List[str] = []
    if not entries:
        reasons.append("missing_toc_classified")
    if start_page is None or end_page is None:
        reasons.append("missing_metadata_range")

    excluded: List[Section] = []
    in_range = 0
    if not reasons and start_page is not None and end_page is not None:
        in_range = len(sections_in_range(entries, start_page, end_page))
        excluded = find_excluded_sections(entries, start_page, end_page, included)

    excluded_types = sorted(
        {str(sec.get("label") or "(unlabeled)") for sec in excluded}
    )
    return {
        "status": _verdict(reasons, excluded),
        "range_start": start_page,
        "range_end": end_page,
        "sections_in_range": in_range,
        "num_excluded": len(excluded),
        "excluded_section_types": excluded_types,
        "excluded_sections": excluded,
        "reasons": reasons,
    }


def describe_excluded_sections(sections: List[Section]) -> str:
    """One-line human-readable summary of violating sections for reports."""
    parts = [
        f"[{sec.get('label') or '(unlabeled)'}] {sec.get('title', '')} (p.{sec.get('page')})"
        for sec in sections
    ]
    return "; ".join(parts)
