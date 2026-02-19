#!/usr/bin/env python3
"""
Re-detect and fix document language labels in PostgreSQL and Qdrant.

The original _detect_language only sampled the first ~2000 chars from
the cover pages of a PDF, which misclassifies bilingual documents
(e.g. French cover page but English body) as the wrong language.

This script re-runs language detection using majority voting across
three sections (beginning, middle, end) of each document, and updates:
  - PostgreSQL docs table   (sys_language column)
  - Qdrant documents collection (sys_language payload field, if present)

Chunks do not carry a language field, so they are not modified.

Usage:
    # Dry run - show what would change
    python scripts/fixes/fix_language_detection.py --data-source uneg --dry-run

    # Only check docs currently tagged as French
    python scripts/fixes/fix_language_detection.py --data-source uneg \\
        --current-lang fr --dry-run

    # Apply fixes
    python scripts/fixes/fix_language_detection.py --data-source uneg

Connection settings are read from .env (QDRANT_HOST, POSTGRES_HOST, etc.)
with sensible localhost defaults. Run inside Docker or set POSTGRES_HOST
appropriately.
"""

import argparse
import csv
import logging
import os
import time
from typing import Optional

import fitz  # PyMuPDF
from dotenv import load_dotenv
from langdetect import detect_langs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language detection (majority-voting)
# ---------------------------------------------------------------------------


def detect_language_improved(filepath: str) -> tuple[str, float]:
    """Detect document language by majority voting across sections.

    Samples text from beginning (skipping cover), middle, and end of
    the document.  Each section votes independently; the majority wins.

    Returns (language_code, max_confidence) tuple.
    """
    try:
        doc = fitz.open(filepath)
        total_pages = len(doc)
        if total_pages == 0:
            doc.close()
            return ("Unknown", 0.0)

        # Build sample ranges
        if total_pages <= 6:
            sample_ranges = [(0, total_pages)]
        else:
            sample_ranges = []
            # Body start: pages 3-12 (skip cover/TOC)
            s = min(3, total_pages - 1)
            sample_ranges.append((s, min(s + 10, total_pages)))
            # Middle
            mid = total_pages // 2
            m_s = max(mid - 4, sample_ranges[-1][1])
            m_e = min(mid + 4, total_pages)
            if m_s < m_e:
                sample_ranges.append((m_s, m_e))
            # End (skip last 2 pages)
            e_s = max(total_pages - 10, sample_ranges[-1][1])
            e_e = max(total_pages - 2, e_s + 1)
            if e_s < e_e:
                sample_ranges.append((e_s, e_e))

        votes: dict[str, int] = {}
        max_conf = 0.0
        for start, end in sample_ranges:
            section_text = ""
            for i in range(start, end):
                page_text = doc[i].get_text()
                if page_text:
                    section_text += page_text + " "
                if len(section_text) > 5000:
                    break
            section_text = " ".join(section_text.split())
            if len(section_text) < 200:
                continue
            results = detect_langs(section_text)
            if results and results[0].prob >= 0.4:
                lang = results[0].lang
                votes[lang] = votes.get(lang, 0) + 1
                max_conf = max(max_conf, results[0].prob)

        doc.close()

        if not votes:
            return ("Unknown", 0.0)
        winner = max(votes, key=votes.get)
        return (winner, max_conf)
    except Exception as e:
        logger.debug("Detection failed for %s: %s", filepath, e)
        return ("Unknown", 0.0)


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


def get_qdrant_client():
    """Create Qdrant client from environment."""
    from qdrant_client import QdrantClient

    host = os.getenv("QDRANT_HOST", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY")
    return QdrantClient(url=host, api_key=api_key)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def scan_documents(
    data_source: str,
    current_lang: Optional[str] = None,
) -> list[tuple[str, str, str, str, float]]:
    """Scan all docs and return list of (doc_id, title, old_lang, new_lang, conf)."""
    conn = get_pg_connection()
    cur = conn.cursor()
    docs_table = f"docs_{data_source}"

    where = "WHERE sys_filepath IS NOT NULL AND sys_language IS NOT NULL"
    params: tuple = ()
    if current_lang:
        where += " AND sys_language = %s"
        params = (current_lang,)

    cur.execute(
        f"SELECT doc_id, map_title, sys_language, sys_filepath "
        f"FROM {docs_table} {where} ORDER BY sys_language, map_title",
        params,
    )
    rows = cur.fetchall()
    conn.close()

    logger.info("Scanning %d documents...", len(rows))
    changes = []
    errors = 0
    t0 = time.time()

    for i, (doc_id, title, old_lang, filepath) in enumerate(rows):
        if not os.path.isabs(filepath):
            filepath = os.path.join(os.getcwd(), filepath)
        if not os.path.exists(filepath):
            errors += 1
            continue

        new_lang, conf = detect_language_improved(filepath)
        if new_lang != "Unknown" and new_lang != old_lang:
            changes.append((doc_id, title or "Untitled", old_lang, new_lang, conf))

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            logger.info(
                "  Processed %d/%d (%.0fs, %d changes so far)",
                i + 1,
                len(rows),
                elapsed,
                len(changes),
            )

    elapsed = time.time() - t0
    logger.info(
        "Scan complete in %.0fs: %d changes out of %d docs (%d files not found)",
        elapsed,
        len(changes),
        len(rows),
        errors,
    )
    return changes


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(changes: list[tuple[str, str, str, str, float]]) -> None:
    """Print a readable report of all proposed changes."""
    if not changes:
        logger.info("No language changes needed.")
        return

    # Transition summary
    transitions: dict[str, int] = {}
    for _, _, old, new, _ in changes:
        key = f"{old} -> {new}"
        transitions[key] = transitions.get(key, 0) + 1

    logger.info("\n=== Language transition summary ===")
    for transition, count in sorted(transitions.items(), key=lambda x: -x[1]):
        logger.info("  %-12s : %d documents", transition, count)
    logger.info("  %-12s : %d documents", "TOTAL", len(changes))

    # Per-document table
    logger.info("\n=== Documents to update ===")
    logger.info("%-38s  %-4s  %-4s  %-5s  %s", "doc_id", "from", "to", "conf", "title")
    logger.info("-" * 110)
    for doc_id, title, old, new, conf in changes:
        logger.info(
            "%-38s  %-4s  %-4s  %4.0f%%  %s",
            doc_id,
            old,
            new,
            conf * 100,
            title[:60],
        )


def write_csv_report(
    changes: list[tuple[str, str, str, str, float]], path: str
) -> None:
    """Write changes to a CSV file."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["doc_id", "title", "old_language", "new_language", "confidence"]
        )
        for doc_id, title, old, new, conf in changes:
            writer.writerow([doc_id, title, old, new, f"{conf:.3f}"])
    logger.info("CSV report written to %s", path)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_postgres(
    data_source: str, changes: list[tuple[str, str, str, str, float]]
) -> int:
    """Update sys_language in the PostgreSQL docs table."""
    conn = get_pg_connection()
    cur = conn.cursor()
    docs_table = f"docs_{data_source}"

    t0 = time.time()
    for doc_id, _, _, new_lang, _ in changes:
        cur.execute(
            f"UPDATE {docs_table} SET sys_language = %s WHERE doc_id = %s",
            (new_lang, doc_id),
        )
    conn.commit()
    conn.close()
    logger.info(
        "PostgreSQL: updated %d rows in %s (%.1fs)",
        len(changes),
        docs_table,
        time.time() - t0,
    )
    return len(changes)


def apply_qdrant_docs(
    data_source: str, changes: list[tuple[str, str, str, str, float]]
) -> int:
    """Update sys_language payload in Qdrant documents collection (if field exists)."""
    client = get_qdrant_client()
    collection = f"documents_{data_source}"

    # Check if collection has sys_language by sampling one point
    sample = client.scroll(collection, limit=1, with_payload=["sys_language"])
    if not sample[0]:
        logger.info("Qdrant %s: collection empty, skipping", collection)
        return 0

    # sys_language may not be in Qdrant docs (it was NOT SET in our check).
    # Still set it so future queries can use it.
    t0 = time.time()
    updated = 0
    batch_size = 50
    for i in range(0, len(changes), batch_size):
        batch = changes[i : i + batch_size]
        for doc_id, _, _, new_lang, _ in batch:
            for attempt in range(3):
                try:
                    client.set_payload(
                        collection,
                        payload={"sys_language": new_lang},
                        points=[doc_id],
                        wait=False,
                    )
                    updated += 1
                    break
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2**attempt)
                    else:
                        logger.warning("Failed to update %s in Qdrant: %s", doc_id, e)
        done = min(i + batch_size, len(changes))
        if done % 200 == 0 or done == len(changes):
            logger.info("  Qdrant docs: %d/%d", done, len(changes))
        time.sleep(0.05)

    logger.info(
        "Qdrant %s: updated %d points (%.1fs)",
        collection,
        updated,
        time.time() - t0,
    )
    return updated


# ---------------------------------------------------------------------------
# Qdrant-only sync
# ---------------------------------------------------------------------------


def sync_qdrant_from_postgres(data_source: str) -> None:
    """Read all sys_language values from PostgreSQL and push to Qdrant."""
    conn = get_pg_connection()
    cur = conn.cursor()
    docs_table = f"docs_{data_source}"
    cur.execute(
        f"SELECT doc_id, sys_language FROM {docs_table} "  # noqa: S608
        "WHERE sys_language IS NOT NULL"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        logger.info("No documents found in %s", docs_table)
        return

    # Build fake changes list: (doc_id, title, old_lang, new_lang, conf)
    changes = [(doc_id, "", "", lang, 1.0) for doc_id, lang in rows]
    logger.info("Syncing %d documents from PostgreSQL to Qdrant...", len(changes))
    apply_qdrant_docs(data_source, changes)
    logger.info("Done!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Re-detect and fix document language labels"
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
    parser.add_argument(
        "--current-lang",
        help="Only re-detect docs currently tagged with this language code (e.g. fr)",
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="Write change report to a CSV file",
    )
    parser.add_argument(
        "--qdrant-only",
        action="store_true",
        help="Sync sys_language from PostgreSQL to Qdrant (skip scan/detection)",
    )
    args = parser.parse_args()

    # Load .env from repo root
    env_path = os.path.join(os.path.dirname(__file__), "../../.env")
    load_dotenv(env_path)

    # Qdrant-only mode: read current values from PG and push to Qdrant
    if args.qdrant_only:
        sync_qdrant_from_postgres(args.data_source)
        return

    # Scan
    changes = scan_documents(args.data_source, args.current_lang)
    print_report(changes)

    if args.csv and changes:
        write_csv_report(changes, args.csv)

    if not changes:
        return

    if args.dry_run:
        logger.info("\nDry run complete. Re-run without --dry-run to apply changes.")
        return

    # Apply
    logger.info("\nApplying %d language updates...", len(changes))
    apply_postgres(args.data_source, changes)
    apply_qdrant_docs(args.data_source, changes)
    logger.info("Done!")


if __name__ == "__main__":
    main()
