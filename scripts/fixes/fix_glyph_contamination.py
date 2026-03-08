#!/usr/bin/env python3
"""
Find and reset documents with glyph contamination in parsed output.

Scans parsed markdown files for two types of garbled output that Docling
produces when PDFs have CIDFont encoding or broken ToUnicode tables:

  1. Raw glyph IDs:  /gid00007 /gid00022 ...
  2. GLYPH markers:  GLYPH<c=3,font=/PNLMND+Calibri-Light>

Documents exceeding the contamination threshold are reset to 'downloaded'
status so they will be re-processed by the pipeline (and now caught by
the improved detection, which marks them as parse_failed).

Usage:
    # Dry run — show what would be reset
    python scripts/fixes/fix_glyph_contamination.py --dry-run

    # Apply — reset contaminated docs to 'downloaded'
    python scripts/fixes/fix_glyph_contamination.py

    # Custom threshold (default: 10%)
    python scripts/fixes/fix_glyph_contamination.py --threshold 0.05

Connection settings are read from .env (POSTGRES_HOST, etc.).
"""

import argparse
import logging
import os
import re
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

_GLYPH_ID_PATTERN = re.compile(r"/gid\d{5}")
_GLYPH_MARKER_PATTERN = re.compile(r"GLYPH<c=\d+,font=[^>]+>")


def get_pg_connection():
    """Create a PostgreSQL connection from .env settings."""
    load_dotenv()
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "evidencelab"),
        user=os.getenv("POSTGRES_USER", "evidencelab"),
        password=os.getenv("POSTGRES_PASSWORD", "evidencelab"),
    )


def check_file_contamination(filepath: Path, threshold: float):
    """Check a markdown file for glyph contamination.

    Returns (is_contaminated, ratio, gid_count, marker_count) or
    (False, 0, 0, 0) if the file cannot be read.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except OSError:
        return False, 0.0, 0, 0

    total = len(content)
    if total < 200:
        return False, 0.0, 0, 0

    gid_matches = _GLYPH_ID_PATTERN.findall(content)
    marker_matches = _GLYPH_MARKER_PATTERN.findall(content)
    glyph_chars = (len(gid_matches) * 9) + sum(len(m) for m in marker_matches)
    ratio = glyph_chars / total

    return (
        ratio >= threshold,
        ratio,
        len(gid_matches),
        len(marker_matches),
    )


def find_contaminated_docs(conn, threshold: float):
    """Scan all parsed docs and return list of contaminated ones."""
    contaminated = []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT doc_id, map_title, sys_parsed_folder, sys_status "
            "FROM docs_worldbank "
            "WHERE sys_parsed_folder IS NOT NULL "
            "ORDER BY doc_id"
        )
        rows = cur.fetchall()

    logger.info("Scanning %d docs with parsed output...", len(rows))

    for doc_id, title, parsed_folder, status in rows:
        parsed_path = Path(parsed_folder)
        md_files = list(parsed_path.glob("*.md")) if parsed_path.exists() else []
        if not md_files:
            continue

        for md_file in md_files:
            is_bad, ratio, gid_count, marker_count = check_file_contamination(
                md_file, threshold
            )
            if is_bad:
                contaminated.append(
                    {
                        "doc_id": doc_id,
                        "title": title or "(no title)",
                        "status": status,
                        "file": str(md_file),
                        "ratio": ratio,
                        "gid_count": gid_count,
                        "marker_count": marker_count,
                    }
                )
                break  # one bad file per doc is enough

    return contaminated


def reset_docs(conn, contaminated, dry_run: bool):
    """Reset contaminated docs to 'downloaded' status."""
    if not contaminated:
        logger.info("No contaminated documents found.")
        return

    logger.info(
        "Found %d contaminated documents (threshold exceeded):",
        len(contaminated),
    )
    for doc in contaminated:
        pct = int(doc["ratio"] * 100)
        details = []
        if doc["gid_count"]:
            details.append(f"{doc['gid_count']} /gid IDs")
        if doc["marker_count"]:
            details.append(f"{doc['marker_count']} GLYPH<> markers")
        logger.info(
            "  %s | %s | %d%% garbled (%s) | status=%s",
            doc["doc_id"],
            doc["title"][:60],
            pct,
            ", ".join(details),
            doc["status"],
        )

    if dry_run:
        logger.info("DRY RUN — no changes made. Re-run without --dry-run to apply.")
        return

    doc_ids = [doc["doc_id"] for doc in contaminated]
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE docs_worldbank "
            "SET sys_status = 'downloaded', "
            "    sys_error_message = 'Reset: glyph contamination in parsed output' "
            "WHERE doc_id = ANY(%s)",
            (doc_ids,),
        )
        updated = cur.rowcount
    conn.commit()
    logger.info("Reset %d documents to 'downloaded' status.", updated)


def main():
    parser = argparse.ArgumentParser(
        description="Find and reset documents with glyph contamination."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be reset without making changes.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.10,
        help="Contamination ratio threshold (default: 0.10 = 10%%).",
    )
    args = parser.parse_args()

    conn = get_pg_connection()
    try:
        contaminated = find_contaminated_docs(conn, args.threshold)
        reset_docs(conn, contaminated, args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
