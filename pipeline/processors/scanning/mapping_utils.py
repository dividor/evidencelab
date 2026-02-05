"""Utilities for scanning field mapping."""

from __future__ import annotations

import re


def sanitize_source_key(key: str) -> str:
    sanitized = key.strip().lower()
    sanitized = re.sub(r"\s+", "_", sanitized)
    sanitized = re.sub(r"[^a-z0-9_]", "", sanitized)
    return sanitized
