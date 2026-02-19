#!/usr/bin/env python3
"""
Fix MacRoman mojibake in PostgreSQL chunk text.

French PDF documents created on old Macs use MacRoman encoding, but
Docling/PyMuPDF decodes them as Windows-1252 (cp1252).  This produces
garbled characters like Ž instead of é, ˆ instead of à, etc.

This script scans chunks_<data_source> in PostgreSQL for mojibake
markers and applies fix_macroman_mojibake() to:
  - sys_text column (main chunk text shown in search results)
  - sys_chunk_elements text snippets inside sys_data JSONB

Usage:
    # Dry run - show what would change
    python scripts/fixes/fix_macroman_mojibake.py --data-source uneg --dry-run

    # Apply fixes
    python scripts/fixes/fix_macroman_mojibake.py --data-source uneg

Note: Embeddings computed from garbled text will remain poor quality.
Re-indexing affected documents through the normal pipeline is the best
way to also fix embeddings.

Connection settings are read from .env (POSTGRES_HOST, etc.) with
sensible localhost defaults.
"""

import argparse
import logging
import os
import time

from dotenv import load_dotenv

from pipeline.utilities.text_cleaning import _MACROMAN_MARKERS, fix_macroman_mojibake

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_pg_connection():
    """Create PostgreSQL connection from environment."""
    import psycopg2

    try:
        from pipeline.db.postgres_client_base import build_postgres_dsn

        return psycopg2.connect(build_postgres_dsn())
    except ImportError:
        return psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            user=os.environ.get("POSTGRES_USER", "evidencelab"),
            password=os.environ.get("POSTGRES_PASSWORD", "evidencelab"),
            dbname=os.environ.get("POSTGRES_DB", "evidencelab"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def has_mojibake_markers(text: str) -> bool:
    """Quick check whether text contains >= 2 MacRoman mojibake markers."""
    if not text:
        return False
    count = 0
    for ch in text:
        if ch in _MACROMAN_MARKERS:
            count += 1
            if count >= 2:
                return True
    return False


def fix_chunk_elements(elements: list) -> tuple[list, bool]:
    """Apply mojibake fix to text fields within sys_chunk_elements."""
    changed = False
    fixed = []
    for elem in elements:
        if isinstance(elem, dict) and elem.get("text"):
            new_text = fix_macroman_mojibake(elem["text"])
            if new_text != elem["text"]:
                changed = True
                elem = {**elem, "text": new_text}
        fixed.append(elem)
    return fixed, changed


# ---------------------------------------------------------------------------
# Scan and fix
# ---------------------------------------------------------------------------


def scan_and_fix(
    data_source: str,
    dry_run: bool,
) -> int:
    """Scan chunks table for mojibake and optionally fix it."""
    import json

    conn = get_pg_connection()
    cur = conn.cursor()
    chunks_table = f"chunks_{data_source}"

    logger.info("Scanning %s for MacRoman mojibake...", chunks_table)
    t0 = time.time()

    # Pre-filter in SQL: only fetch rows containing at least one marker char.
    # This avoids loading the entire (potentially huge) chunks table.
    marker_chars = list(_MACROMAN_MARKERS)
    like_clauses = " OR ".join(["sys_text LIKE %s"] * len(marker_chars))
    like_params = tuple(f"%{ch}%" for ch in marker_chars)

    cur.execute(
        f"SELECT chunk_id, doc_id, sys_text, sys_data "  # noqa: S608
        f"FROM {chunks_table} WHERE sys_text IS NOT NULL "
        f"AND ({like_clauses})",
        like_params,
    )
    rows = cur.fetchall()
    logger.info(
        "  Found %d candidate chunks with marker chars (%.1fs)",
        len(rows),
        time.time() - t0,
    )

    fixes: list[tuple[str, str, str | None]] = []  # (chunk_id, new_text, new_data_json)
    affected_docs: set[str] = set()

    for chunk_id, doc_id, sys_text, sys_data in rows:
        new_text = fix_macroman_mojibake(sys_text)
        text_changed = new_text != sys_text

        new_data_json = None
        data_changed = False
        if sys_data and isinstance(sys_data, dict):
            elements = sys_data.get("sys_chunk_elements", [])
            if elements:
                fixed_elems, data_changed = fix_chunk_elements(elements)
                if data_changed:
                    new_data_json = json.dumps(
                        {**sys_data, "sys_chunk_elements": fixed_elems}
                    )

        if text_changed or data_changed:
            fixes.append((chunk_id, new_text, new_data_json))
            affected_docs.add(doc_id)

    elapsed = time.time() - t0
    logger.info(
        "  Found %d chunks to fix across %d documents (%.1fs)",
        len(fixes),
        len(affected_docs),
        elapsed,
    )

    if not fixes:
        logger.info("No mojibake found.")
        return 0

    # Show samples
    for chunk_id, new_text, _ in fixes[:5]:
        preview = new_text[:120].replace("\n", " ")
        logger.info("  [sample] %s: %s...", chunk_id, preview)

    if dry_run:
        logger.info(
            "\nDry run complete. %d chunks would be fixed. "
            "Re-run without --dry-run to apply.",
            len(fixes),
        )
        return len(fixes)

    # Apply
    logger.info("\nApplying %d chunk updates...", len(fixes))
    t0 = time.time()
    batch_size = 100

    for i in range(0, len(fixes), batch_size):
        batch = fixes[i : i + batch_size]
        for chunk_id, new_text, new_data_json in batch:
            if new_data_json is not None:
                cur.execute(
                    f"UPDATE {chunks_table} "  # noqa: S608
                    "SET sys_text = %s, sys_data = %s::jsonb "
                    "WHERE chunk_id = %s",
                    (new_text, new_data_json, chunk_id),
                )
            else:
                cur.execute(
                    f"UPDATE {chunks_table} "  # noqa: S608
                    "SET sys_text = %s WHERE chunk_id = %s",
                    (new_text, chunk_id),
                )
        conn.commit()
        done = min(i + batch_size, len(fixes))
        logger.info("  Updated %d/%d chunks", done, len(fixes))
        time.sleep(0.05)

    logger.info(
        "PostgreSQL: updated %d chunks in %s (%.1fs)",
        len(fixes),
        chunks_table,
        time.time() - t0,
    )
    cur.close()
    conn.close()
    return len(fixes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Fix MacRoman mojibake in PostgreSQL chunk text"
    )
    parser.add_argument(
        "--data-source",
        required=True,
        help="Data source name (e.g. uneg)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without applying them",
    )
    args = parser.parse_args()

    # Load .env from repo root
    env_path = os.path.join(os.path.dirname(__file__), "../../.env")
    load_dotenv(env_path)

    scan_and_fix(args.data_source, args.dry_run)


if __name__ == "__main__":
    main()
