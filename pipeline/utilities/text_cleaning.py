"""Helpers for cleaning extracted text content."""

import re
import unicodedata


def clean_text(text: str) -> str:
    """Do robust text cleaning to fix encoding issues."""
    if not text:
        return text

    # 1. First, normalize unicode to ensure consistency
    cleaned = unicodedata.normalize("NFKC", text)

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
