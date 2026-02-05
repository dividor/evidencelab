"""Docling-derived TOC helpers."""

import re
from typing import Any, List

from pipeline.processors.parsing.toc_normalize import _parse_toc_lines


def generate_toc_from_docling(_parser, result: Any) -> str:
    """Generate TOC string from Docling result."""
    toc_lines: List[str] = []
    for item, level in _iter_section_headers(result):
        if _should_skip_heading_text(item.text):
            continue
        toc_lines.append(_format_docling_toc_entry(item, level))
    return "\n".join(toc_lines)


def _iter_section_headers(result: Any):
    for item, level in result.document.iterate_items():
        if hasattr(item, "text") and type(item).__name__ == "SectionHeaderItem":
            yield item, level


def _format_docling_toc_entry(item: Any, level: int) -> str:
    indent = "  " * level
    heading_level = _resolve_heading_level(item)
    page_num = _resolve_page_num(item)
    return f"{indent}[H{heading_level}] {item.text[:80]} | page {page_num}"


def _resolve_heading_level(item: Any) -> str | int:
    heading_level = getattr(item, "level", -1)
    if heading_level != -1:
        return heading_level + 1
    return "?"


def _resolve_page_num(item: Any) -> str | int:
    if hasattr(item, "prov") and item.prov:
        for prov_item in item.prov:
            if hasattr(prov_item, "page_no"):
                return prov_item.page_no
    return "?"


def _should_skip_heading_text(text: str) -> bool:
    stripped = text.strip()
    match = re.match(r"^(?P<num>\d{2,3})\.\s+\S", stripped)
    if not match:
        return False
    number = int(match.group("num"))
    return number >= 50


def _is_docling_toc_low_quality(toc_string: str) -> bool:
    entries = [entry for entry in _parse_toc_lines(toc_string) if entry.get("parsed")]
    if len(entries) < 5:
        return True

    figure_table_count = sum(
        1 for entry in entries if _looks_like_figure_or_table(entry["title"])
    )
    question_count = sum(1 for entry in entries if "?" in entry["title"])

    figure_table_ratio = figure_table_count / len(entries)
    question_ratio = question_count / len(entries)

    # Heuristic: very large TOC dominated by figures/tables or long question headings
    if len(entries) >= 40 and (figure_table_ratio >= 0.2 or question_ratio >= 0.3):
        return True

    return False


def _looks_like_figure_or_table(title: str) -> bool:
    lowered = title.strip().lower()
    return lowered.startswith("figure ") or lowered.startswith("table ")
