"""Filename sanitization helpers."""

import re
import unicodedata


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to be lowercase, space-free, and special-character-free.

    Rules:
    - Convert to lowercase
    - Replace spaces with underscores
    - Remove all special characters except alphanumeric, underscores, hyphens, and dots
    - Ensure no leading/trailing underscores or dots
    - Collapse multiple underscores/hyphens
    """
    if not filename:
        return "untitled"

    # Lowercase
    clean = filename.lower()

    # Decompose unicode so accented chars become base letter + combining mark
    clean = unicodedata.normalize("NFD", clean)

    # Replace spaces with underscores
    clean = clean.replace(" ", "_")

    # Keep only alphanumeric, underscores, hyphens, and dots
    # Combining marks from NFD decomposition are stripped, base letters kept
    clean = re.sub(r"[^a-z0-9_.-]", "", clean)

    # Collapse multiple underscores
    clean = re.sub(r"_+", "_", clean)

    # Collapse multiple dots
    clean = re.sub(r"\.{2,}", ".", clean)

    # Remove leading/trailing underscores and dots
    clean = clean.strip("_.")

    if not clean:
        return "untitled"

    return clean
