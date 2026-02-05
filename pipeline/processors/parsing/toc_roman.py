"""Roman numeral and front-matter annotations for TOC lines."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import fitz

logger = logging.getLogger(__name__)


def detect_roman_page_labels(filepath: str, batch_size: int = 20) -> Dict[int, str]:
    """Detect roman numeral page labels (page_number -> roman token)."""
    roman_labels: Dict[int, str] = {}
    try:
        doc = fitz.open(filepath)
    except Exception as exc:
        logger.warning("Unable to open PDF for roman page scan: %s", exc)
        return roman_labels
    with doc:
        page_count = doc.page_count
        start = 0
        seen_roman = False
        while start < page_count:
            end = min(start + batch_size, page_count)
            batch_has_roman = False
            for page_index in range(start, end):
                page = doc.load_page(page_index)
                words = page.get_text("words")
                if not words:
                    continue
                height = page.rect.height
                if not height:
                    continue
                roman_tokens = _roman_tokens_from_page(words, height)
                if roman_tokens:
                    batch_has_roman = True
                    roman_labels[page_index + 1] = roman_tokens[0]
            if batch_has_roman:
                seen_roman = True
            elif seen_roman:
                break
            start = end

    return roman_labels


def _is_roman_token(token: str) -> bool:
    stripped = token.strip()
    if not stripped or stripped.isdigit():
        return False
    if len(stripped) > 6:
        return False
    normalized = stripped.upper()
    if "M" in normalized:
        return False
    roman_pattern = re.compile(
        r"^M{0,4}(CM|CD|D?C{0,3})" r"(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
    )
    return bool(roman_pattern.fullmatch(normalized))


def _roman_to_int(token: str) -> Optional[int]:
    if not token:
        return None
    normalized = token.strip().upper()
    if not normalized:
        return None
    if "M" in normalized:
        return None
    roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev_value = 0
    for char in reversed(normalized):
        value = roman_map.get(char)
        if value is None:
            return None
        if value < prev_value:
            total -= value
        else:
            total += value
            prev_value = value
    return total


def _roman_tokens_from_page(words: List[List[Any]], height: float) -> List[str]:
    roman_tokens: List[str] = []
    for word in words:
        token = word[4]
        if not _is_roman_token(token):
            continue
        if word[1] <= height * 0.15 or word[3] >= height * 0.85:
            roman_tokens.append(token)
    return roman_tokens


def annotate_toc_with_roman(toc_string: str, roman_labels: Dict[int, str]) -> str:
    if not toc_string:
        return toc_string
    annotated_lines: List[str] = []
    pattern = re.compile(r"^(?P<prefix>.*?\|\s*page\s*)(?P<page>\d+)(?P<suffix>\s*)$")
    for line in toc_string.splitlines():
        match = pattern.match(line)
        if not match:
            annotated_lines.append(line)
            continue
        page = int(match.group("page"))
        roman_label = roman_labels.get(page)
        if roman_label:
            annotated_lines.append(
                f"{match.group('prefix')}{page} ({roman_label}){match.group('suffix')}"
            )
        else:
            annotated_lines.append(line)
    return "\n".join(annotated_lines)


def annotate_toc_with_front_matter(
    toc_string: str,
    roman_labels: Dict[int, str],
    total_pages: Optional[int],
) -> str:
    """Annotate TOC lines at/before roman boundary with a [Front] marker."""
    if not toc_string or not roman_labels:
        return toc_string

    roman_entries = _collect_roman_entries(roman_labels, total_pages)
    roman_end = _resolve_roman_end(roman_entries, roman_labels)
    return _annotate_front_matter_lines(toc_string, roman_end)


def _resolve_front_run_end(roman_entries: List[Tuple[int, int]]) -> Optional[int]:
    if not roman_entries:
        return None
    runs: List[Tuple[int, int, int]] = []
    run_start = roman_entries[0][0]
    run_end = roman_entries[0][0]
    run_len = 1
    prev_value = roman_entries[0][1]
    for page, value in roman_entries[1:]:
        if value == 1 and prev_value > 1:
            runs.append((run_len, run_start, run_end))
            break
        if value < prev_value:
            runs.append((run_len, run_start, run_end))
            run_start = page
            run_end = page
            run_len = 1
            prev_value = value
            continue
        run_end = page
        run_len += 1
        prev_value = value
    else:
        runs.append((run_len, run_start, run_end))

    long_runs = [run for run in runs if run[0] >= 3]
    if not long_runs:
        return None
    _, _, roman_end = long_runs[-1]
    return roman_end


def _collect_roman_entries(
    roman_labels: Dict[int, str], total_pages: Optional[int]
) -> List[Tuple[int, int]]:
    roman_entries: List[Tuple[int, int]] = []
    for page, roman in roman_labels.items():
        roman_value = _roman_to_int(roman)
        if roman_value is None:
            continue
        if _page_beyond_front_threshold(page, total_pages):
            continue
        roman_entries.append((page, roman_value))
    return roman_entries


def _page_beyond_front_threshold(page: int, total_pages: Optional[int]) -> bool:
    if total_pages and total_pages > 0 and page > total_pages / 3:
        return True
    return False


def _resolve_roman_end(
    roman_entries: List[Tuple[int, int]], roman_labels: Dict[int, str]
) -> Optional[int]:
    if not roman_entries:
        return None

    roman_entries = sorted(set(roman_entries))
    roman_by_page = {page: roman for page, roman in roman_labels.items()}
    lower_entries = _filter_lowercase_entries(roman_entries, roman_by_page)

    if _has_monotonic_run(lower_entries, min_len=3):
        roman_entries = _filter_lowercase_entries(roman_entries, roman_by_page)
        if not roman_entries:
            return None

    return _resolve_front_run_end(roman_entries)


def _filter_lowercase_entries(
    roman_entries: List[Tuple[int, int]], roman_by_page: Dict[int, str]
) -> List[Tuple[int, int]]:
    return [
        (page, value)
        for page, value in roman_entries
        if roman_by_page.get(page, "").strip().islower()
    ]


def _has_monotonic_run(entries: List[Tuple[int, int]], min_len: int) -> bool:
    if len(entries) < min_len:
        return False
    run_len = 1
    prev_value = entries[0][1]
    for _, value in entries[1:]:
        if value < prev_value:
            run_len = 1
            prev_value = value
            continue
        run_len += 1
        prev_value = value
        if run_len >= min_len:
            return True
    return False


def _annotate_front_matter_lines(toc_string: str, roman_end: Optional[int]) -> str:
    annotated_lines: List[str] = []
    pattern = re.compile(
        r"^(?P<prefix>.*?\|\s*page\s*)(?P<page>\d+)"
        r"(?P<roman>\s*\([^)]+\))?(?P<fm>\s*\[Front\])?(?P<suffix>\s*)$"
    )
    for line in toc_string.splitlines():
        match = pattern.match(line)
        if not match:
            annotated_lines.append(line)
            continue
        page = int(match.group("page"))
        annotated_lines.append(
            _format_front_matter_line(match, page <= (roman_end or 0))
        )

    return "\n".join(annotated_lines)


def _format_front_matter_line(match: re.Match, mark_front: bool) -> str:
    if mark_front:
        return (
            f"{match.group('prefix')}{match.group('page')}"
            f"{match.group('roman') or ''} [Front]{match.group('suffix')}"
        )
    return (
        f"{match.group('prefix')}{match.group('page')}"
        f"{match.group('roman') or ''}{match.group('suffix')}"
    )
