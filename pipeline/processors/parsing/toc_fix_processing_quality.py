"""TOC quality validation helpers."""

import re


def validate_toc_quality(anchors: list) -> tuple[bool, str]:
    """Validate TOC anchor quality using multiple heuristics."""
    short_check = _check_short_toc(anchors)
    if short_check is not None:
        return short_check

    valid_pages = _collect_valid_pages(anchors)
    page_check = _check_page_numbers(valid_pages, len(anchors))
    if page_check is not None:
        return page_check

    clean_headings = _clean_headings(anchors)
    if _too_many_short_headings(clean_headings):
        return False, "Too many very short headings"

    if _has_numbering_pattern(clean_headings):
        return True, "Valid TOC with numbering pattern"

    if _has_common_headings(clean_headings):
        return True, "Valid TOC with common headings"

    if len(anchors) >= 5 and len(valid_pages) >= 3:
        return True, "Accepting TOC with sufficient anchors and page numbers"

    return False, "TOC does not meet quality heuristics"


def _check_short_toc(anchors: list) -> tuple[bool, str] | None:
    if len(anchors) >= 3:
        return None
    if len(anchors) not in {1, 2}:
        return False, f"Too few anchors: {len(anchors)} (minimum 3)"

    clean_texts = []
    for anchor in anchors:
        clean_heading = re.sub(r"\[H\d+\]\s*", "", anchor["text"]).strip()
        clean_heading = re.sub(
            r"^(Chapter\s+\d+[.:]?\s*|\d+[.:]\s*)",
            "",
            clean_heading,
            flags=re.IGNORECASE,
        ).strip()
        clean_texts.append(clean_heading)

    if _short_toc_has_keywords(clean_texts):
        return True, f"Valid short TOC with {len(anchors)} anchors"
    if _short_toc_has_pages(clean_texts, anchors):
        return True, f"Valid short TOC with {len(anchors)} anchors"
    return False, f"Too few anchors: {len(anchors)} (minimum 3)"


def _short_toc_has_keywords(clean_texts: list) -> bool:
    if not all(len(text) >= 4 for text in clean_texts):
        return False
    common_keywords = [
        r"introduction|introducci[oó]n|introdução|introduction|введение",
        r"summary|resumen|resumo|résumé|zusammenfassung|摘要",
        r"findings|conclusions|conclusiones|conclusões|conclusions|выводы",
        r"recommendations|recomendaciones|recomendações|recommandations|empfehlungen",
        r"methodology|metodología|metodologia|méthodologie|methodik",
        r"annex|anexo|annexe|anhang|приложение|附录",
    ]
    return any(
        re.search(pattern, text.lower())
        for text in clean_texts
        for pattern in common_keywords
    )


def _short_toc_has_pages(clean_texts: list, anchors: list) -> bool:
    if not all(len(text) >= 4 for text in clean_texts):
        return False
    return any(anchor.get("page", -1) > 0 for anchor in anchors)


def _collect_valid_pages(anchors: list) -> list:
    return [a["page"] for a in anchors if a["page"] > 0]


def _check_page_numbers(
    valid_pages: list, anchor_count: int
) -> tuple[bool, str] | None:
    if len(valid_pages) < 2:
        if anchor_count >= 4:
            return True, "Accepting TOC with many anchors despite missing page numbers"
        return False, "Too few valid page numbers"
    if _is_monotonic(valid_pages):
        return None
    if any(
        valid_pages[i] - valid_pages[i + 1] > 5 for i in range(len(valid_pages) - 1)
    ):
        return False, "Page numbers are not monotonically increasing"
    return None


def _is_monotonic(valid_pages: list) -> bool:
    return all(
        valid_pages[i] <= valid_pages[i + 1] for i in range(len(valid_pages) - 1)
    )


def _clean_headings(anchors: list) -> list:
    clean_headings = []
    for anchor in anchors:
        text = anchor["text"]
        clean = re.sub(r"\[H\d+\]\s*", "", text).strip()
        clean = re.sub(r"^[\d\.\s]*", "", clean).strip()
        clean_headings.append(clean)
    return clean_headings


def _too_many_short_headings(clean_headings: list) -> bool:
    return sum(1 for h in clean_headings if len(h) >= 4) < len(clean_headings) * 0.6


def _has_numbering_pattern(clean_headings: list) -> bool:
    numbering_matches = sum(1 for h in clean_headings if re.match(r"^\d+(\.\d+)*", h))
    return numbering_matches >= len(clean_headings) * 0.5


def _has_common_headings(clean_headings: list) -> bool:
    common_words = [
        "introduction",
        "summary",
        "findings",
        "conclusion",
        "recommendation",
        "annex",
        "appendix",
        "methodology",
    ]
    return any(
        any(word in heading.lower() for word in common_words)
        for heading in clean_headings[:5]
    )
