"""Helpers for cleaning extracted text content."""

import re
import unicodedata

# ---------------------------------------------------------------------------
# MacRoman mojibake repair
# ---------------------------------------------------------------------------
# PDFs created on old Macs sometimes have MacRoman-encoded bytes that
# Docling/PyMuPDF decodes as Windows-1252 (cp1252).  The characters below
# are cp1252 interpretations that map to common French accented letters in
# MacRoman.  They are extremely unlikely to appear in correctly-encoded
# French/English/Spanish text (they are Czech/Slovak letters or typographic
# modifiers), so substituting them is safe.

_MACROMAN_SAFE_MAP: dict[str, str] = {
    "\u02c6": "\u00e0",  # ˆ (modifier circumflex) -> à
    "\u017d": "\u00e9",  # Ž (Z-caron) -> é
    "\u017e": "\u00fb",  # ž (z-caron) -> û
    "\u0160": "\u00e4",  # Š (S-caron) -> ä
    "\u0161": "\u00f6",  # š (s-caron) -> ö
}

_MACROMAN_MARKERS = frozenset(_MACROMAN_SAFE_MAP.keys())

# Õ (U+00D5) -> right single quote (U+2019) only between word characters.
# In MacRoman 0xD5 is the right single quote used as an apostrophe.
_CONTEXTUAL_APOSTROPHE = re.compile(r"(?<=\w)\u00d5(?=\w)")

_MACROMAN_TRANSLATE = str.maketrans(_MACROMAN_SAFE_MAP)


def fix_macroman_mojibake(text: str) -> str:
    """Fix MacRoman bytes that were incorrectly decoded as cp1252.

    Only applies when >=2 strong marker characters are detected,
    preventing false positives on text that legitimately contains
    Czech/Slovak letters or typographic modifiers.
    """
    if not text:
        return text

    marker_count = sum(1 for ch in text if ch in _MACROMAN_MARKERS)
    if marker_count < 2:
        return text

    result = text.translate(_MACROMAN_TRANSLATE)
    result = _CONTEXTUAL_APOSTROPHE.sub("\u2019", result)
    return result


# ---------------------------------------------------------------------------
# Main cleaning function
# ---------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """Do robust text cleaning to fix encoding issues."""
    if not text:
        return text

    # 0. Fix MacRoman mojibake (before NFKC normalisation)
    cleaned = fix_macroman_mojibake(text)

    # 1. Normalize unicode to ensure consistency
    cleaned = unicodedata.normalize("NFKC", cleaned)

    # 2. Handle the specific Replacement Character (U+FFFD) ''
    # This often replaces 'ti', 'fi', 'fl', 'ff' in corrupted PDFs
    if "\ufffd" in cleaned:
        # Common patterns with replacement character
        # We use [\ufffd] to match the literal character
        replacements_ufffd = [
            (r"Na[\ufffd]onal", "National"),
            (r"na[\ufffd]onal", "national"),
            (r"Informa[\ufffd]on", "Information"),
            (r"informa[\ufffd]on", "information"),
            (r"Organiza[\ufffd]on", "Organization"),
            (r"organiza[\ufffd]on", "organization"),
            (r"Evalua[\ufffd]on", "Evaluation"),
            (r"evalua[\ufffd]on", "evaluation"),
            (r"Situa[\ufffd]on", "Situation"),
            (r"situa[\ufffd]on", "situation"),
            (r"Funcon", "Function"),  # sometimes dropped
            (r"Func[\ufffd]on", "Function"),
            (r"funcon", "function"),
            (r"func[\ufffd]on", "function"),
            (r"Forma[\ufffd]ve", "Formative"),  # Added missing pattern
            (r"forma[\ufffd]ve", "formative"),
            (r"Acon", "Action"),
            (r"Ac[\ufffd]on", "Action"),
            (r"acon", "action"),
            (r"ac[\ufffd]on", "action"),
            (r"Popula[\ufffd]on", "Population"),
            (r"popula[\ufffd]on", "population"),
            (r"Idenfy", "Identify"),
            (r"Iden[\ufffd]fy", "Identify"),
            (r"iden[\ufffd]fy", "identify"),
            (r"Nofy", "Notify"),
            (r"No[\ufffd]fy", "Notify"),
            (r"no[\ufffd]fy", "notify"),
            (r"Effecve", "Effective"),
            (r"Effec[\ufffd]ve", "Effective"),
            (r"effec[\ufffd]ve", "effective"),
            (r"Opera[\ufffd]on", "Operational"),
            (r"opera[\ufffd]on", "operational"),
            (r"Nutri[\ufffd]on", "Nutrition"),
            (r"nutri[\ufffd]on", "nutrition"),
            (r"Educa[\ufffd]on", "Education"),
            (r"educa[\ufffd]on", "education"),
            (r"Loca[\ufffd]on", "Location"),
            (r"loca[\ufffd]on", "location"),
            (r"Protec[\ufffd]on", "Protection"),
            (r"protec[\ufffd]on", "protection"),
            (r"Sec[\ufffd]on", "Section"),
            (r"sec[\ufffd]on", "section"),
            (r"Communica[\ufffd]on", "Communication"),
            (r"communica[\ufffd]on", "communication"),
            (r"Descrip[\ufffd]on", "Description"),
            (r"descrip[\ufffd]on", "description"),
            (r"Bulle[\ufffd]n", "Bulletin"),
            (r"bulle[\ufffd]n", "bulletin"),
            (r"Solu[\ufffd]on", "Solution"),
            # Ligature-like suffix repairs (wildcards with \ufffd)
            (r"[\ufffd]on\b", "tion"),  # e.g. "acon" -> "action"
            (r"[\ufffd]ve\b", "tive"),  # e.g. "effecve" -> "effective"
        ]

        for pattern, replacement in replacements_ufffd:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        # Generic fallback for remaining  if it looks like 'ti'
        # e.g. "mulple" -> "multiple"
        cleaned = re.sub(
            r"([a-z])[\ufffd]([a-z])", r"\1ti\2", cleaned, flags=re.IGNORECASE
        )

    # 3. Handle cases where the ligature was completely dropped (e.g. "Naonal")
    replacements_dropped = [
        (r"Naonal", "National"),
        (r"Formave", "Formative"),
        (r"evaluaon", "evaluation"),
        (r"situaon", "situation"),
        (r"Organizaon", "Organization"),
        (r"Bullen", "Bulletin"),
        (r"funcon", "function"),
        (r"acon", "action"),
        (r"populaon", "population"),
        (r"idenfy", "identify"),
        (r"nofy", "notify"),
        (r"effecve", "effective"),
        (r"Descripon", "Description"),  # Added based on browser findings
        (r"descripon", "description"),
        (r"pracce", "practice"),
        (r"parcipant", "participant"),
        (r"mul\b", "multi"),  # careful with 'mul'
        (r"addional", "additional"),
        (r"operaonal", "operational"),
        (r"nutrion", "nutrition"),
        (r"educaon", "education"),
        (r"locaon", "location"),
        (r"protecon", "protection"),
        (r"secon", "section"),
        (r"Soluon", "Solution"),
        (r"informon", "information"),
        (r"communicaon", "communication"),
    ]

    for pattern, replacement in replacements_dropped:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    return cleaned
