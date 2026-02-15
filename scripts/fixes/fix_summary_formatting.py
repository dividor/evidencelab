#!/usr/bin/env python3
"""
Fix legacy summary formatting in PostgreSQL so headings render correctly.

Newly ingested documents use proper markdown headings:
    ## Summary
    ### Context
    ### Findings
    ### Recommendations
    ## Topics
    ## Core Concepts and Terms
    ## Methodological Patterns

Legacy summaries have several broken patterns:
    1. Bullet+bold:  "- **Summary:** ..."   (3,834 docs)
    2. H1 headings:  "# Summary ..."        (329 docs)
    3. Code-fenced:  "```markdown\n# ..."    (93 docs)
    4. H3+colon:     "### Summary: ..."      (2 docs)
    5. Bold only:    "**Summary** ..."       (1 doc)

This script applies regex-based fixes directly — no LLM re-summarization needed.

Usage:
    python scripts/fixes/fix_summary_formatting.py --data-source uneg --dry-run
    python scripts/fixes/fix_summary_formatting.py --data-source uneg
"""

import argparse
import logging
import os
import re
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from pipeline.db import get_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Heading hierarchy matching the prompt templates (summary_final.j2)
H2_SECTIONS = {
    "Summary",
    "Topics",
    "Core Concepts and Terms",
    "Methodological Patterns",
}
H3_SECTIONS = {"Context", "Findings", "Recommendations"}
ALL_SECTIONS = H2_SECTIONS | H3_SECTIONS

# Build alternation pattern for section names (longest first to avoid partial matches)
SECTION_NAMES = "|".join(sorted(ALL_SECTIONS, key=len, reverse=True))


def heading_for(name: str) -> str:
    """Return the correct markdown heading for a section name."""
    level = "##" if name in H2_SECTIONS else "###"
    return f"{level} {name}"


def fix_bullet_bold(text: str) -> str:
    """
    Fix pattern: - **Summary:** ... / - **Context:** ...
    Also handles: * **Summary:** ..., bullet unicode variants, and **Summary:** without bullet.
    """
    pattern = re.compile(
        r"^\s*(?:[-*\u2022\u2023\u25E6\u2043\u2219]\s+)?"
        r"\*\*(" + SECTION_NAMES + r")\s*:?\s*\*\*\s*:?\s*",
        re.MULTILINE,
    )

    def repl(m):
        return heading_for(m.group(1)) + "\n\n"

    return pattern.sub(repl, text)


def fix_h1_headings(text: str) -> str:
    """Fix pattern: # Summary ... -> ## Summary ..."""
    pattern = re.compile(
        r"^#\s+(" + SECTION_NAMES + r")\s*:?\s*$",
        re.MULTILINE,
    )

    def repl(m):
        return heading_for(m.group(1))

    return pattern.sub(repl, text)


def fix_code_fence(text: str) -> str:
    """Strip ```markdown ... ``` wrapping, then fix headings inside."""
    # Remove opening code fence (with optional language tag)
    text = re.sub(r"^```(?:markdown|md)?\s*\n", "", text)
    # Remove closing code fence
    text = re.sub(r"\n```\s*$", "", text)
    # The content inside typically uses # headings, so fix those too
    return fix_h1_headings(text)


def fix_h3_with_colon(text: str) -> str:
    """Fix pattern: ### Summary: ... -> ## Summary (correct level, no colon)."""
    pattern = re.compile(
        r"^###\s+(" + SECTION_NAMES + r")\s*:\s*$",
        re.MULTILINE,
    )

    def repl(m):
        return heading_for(m.group(1))

    return pattern.sub(repl, text)


def classify_and_fix(text: str) -> tuple[str, str]:
    """
    Classify the broken pattern and return (pattern_name, fixed_text).
    Returns (None, text) if already properly formatted.
    """
    if re.match(r"^\s*##\s+Summary", text):
        return None, text

    if re.match(r"^```", text):
        return "code-fence", fix_code_fence(text)

    if re.match(r"^\s*(?:[-*\u2022\u2023\u25E6\u2043\u2219]\s+)?\*\*", text):
        return "bullet-bold", fix_bullet_bold(text)

    if re.match(r"^#\s+Summary", text):
        return "h1", fix_h1_headings(text)

    if re.match(r"^###\s+Summary", text):
        return "h3-colon", fix_h3_with_colon(text)

    # Unknown pattern — don't touch it
    return "unknown", text


def fix_summaries(data_source: str, dry_run: bool = True, limit: int = 0):
    db = get_db(data_source)
    docs_table = db.pg.docs_table

    logger.info("Querying broken summaries from %s ...", docs_table)

    with db.pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, sys_full_summary FROM {docs_table} "
                f"WHERE sys_full_summary IS NOT NULL "
                f"AND sys_full_summary != '' "
                f"AND sys_full_summary !~ '^## Summary'"
            )
            rows = cur.fetchall()

    logger.info("Found %d summaries with broken formatting", len(rows))

    if limit > 0:
        rows = rows[:limit]
        logger.info("Limiting to %d rows", limit)

    stats: dict[str, int] = {}
    fixed_rows = []

    for doc_id, summary in rows:
        pattern, fixed = classify_and_fix(summary)
        if pattern is None:
            continue
        stats[pattern] = stats.get(pattern, 0) + 1
        fixed_rows.append((doc_id, fixed))

    logger.info("Pattern breakdown:")
    for pattern, count in sorted(stats.items(), key=lambda x: -x[1]):
        logger.info("  %-15s %d", pattern, count)
    logger.info("Total to fix: %d", len(fixed_rows))

    if not fixed_rows:
        return

    # Show before/after for first example
    sample_id, sample_fixed = fixed_rows[0]
    sample_original = next(s for d, s in rows if d == sample_id)
    logger.info("--- Example (doc_id=%s) ---", sample_id)
    logger.info("BEFORE (first 500 chars):\n%s", sample_original[:500])
    logger.info("AFTER  (first 500 chars):\n%s", sample_fixed[:500])
    logger.info("---")

    if dry_run:
        logger.info("DRY RUN — no changes written")
        return

    logger.info("Applying fixes...")
    updated = 0
    errors = 0

    with db.pg._get_conn() as conn:
        with conn.cursor() as cur:
            for doc_id, fixed_summary in fixed_rows:
                try:
                    cur.execute(
                        f"UPDATE {docs_table} "
                        f"SET sys_full_summary = %s "
                        f"WHERE doc_id = %s",
                        (fixed_summary, doc_id),
                    )
                    updated += 1
                except Exception as e:
                    logger.error("Failed to update doc %s: %s", doc_id, e)
                    errors += 1

                if updated % 500 == 0 and updated > 0:
                    conn.commit()
                    logger.info("  Committed %d/%d ...", updated, len(fixed_rows))

            conn.commit()

    logger.info("Done. Updated: %d, Errors: %d", updated, errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix legacy summary heading formatting in PostgreSQL"
    )
    parser.add_argument(
        "--data-source", default="uneg", help="Data source name (default: uneg)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without updating",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Limit number of docs to process (0 = all)"
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN MODE — no changes will be made")

    fix_summaries(args.data_source, dry_run=args.dry_run, limit=args.limit)
