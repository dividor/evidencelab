#!/usr/bin/env python3
"""
Fix SDG separator issue in JSON metadata files.

The sdgs field in JSON files has values concatenated without separators:
"SDG1 - No PovertySDG10 - Reduced Inequalities..."

This script adds "; " separator between SDG values:
"SDG1 - No Poverty; SDG10 - Reduced Inequalities; ..."

Usage:
    python scripts/maintenance/fix_json_sdg_separators.py \\
        --data-dir /path/to/data/uneg/pdfs
    python scripts/maintenance/fix_json_sdg_separators.py \\
        --data-dir /path/to/data/uneg/pdfs --dry-run
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def fix_sdg_separators_in_files(data_dir: str, dry_run: bool = False):
    """Fix SDG separators in all JSON files."""
    logger.info(f"Fixing SDG separators in JSON files under: {data_dir}")
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    data_path = Path(data_dir)
    if not data_path.exists():
        logger.error(f"Directory does not exist: {data_dir}")
        return

    # Find all JSON files
    json_files = list(data_path.glob("**/*.json"))
    logger.info(f"Found {len(json_files)} JSON files")

    # Track stats
    files_with_sdgs = 0
    files_needing_fixes = 0
    files_updated = 0

    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "sdgs" not in data:
                continue

            files_with_sdgs += 1
            sdgs = data["sdgs"]

            # Check if it needs fixing (has "SDG" followed by another "SDG" without separator)
            if "SDG" not in sdgs or sdgs.count("SDG") < 2:
                continue

            # Check if already properly formatted (all SDGs separated)
            num_sdgs = sdgs.count("SDG")
            num_separators = sdgs.count("; ")
            if num_separators == num_sdgs - 1:
                continue

            files_needing_fixes += 1

            # Show example before first 3 files
            if files_needing_fixes <= 3:
                fixed_sdg = re.sub(r"(SDG\d+[^;]*?)(?=SDG\d)", r"\1; ", sdgs)
                logger.info(f"\nExample fix in: {json_file.name}")
                logger.info(f"  Before: {sdgs[:100]}...")
                logger.info(f"  After:  {fixed_sdg[:100]}...")

            if dry_run:
                continue

            # Fix the SDGs - use lookahead for "SDG" followed by digit
            fixed_sdg = re.sub(r"(SDG\d+[^;]*?)(?=SDG\d)", r"\1; ", sdgs)
            data["sdgs"] = fixed_sdg

            # Write back to file
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            files_updated += 1

            if files_updated % 100 == 0:
                logger.info(f"  Updated {files_updated}/{files_needing_fixes} files...")

        except Exception as e:
            logger.error(f"Error processing {json_file}: {e}")
            continue

    logger.info(f"\n{'='*80}")
    logger.info("Summary:")
    logger.info(f"  Total JSON files: {len(json_files)}")
    logger.info(f"  Files with SDGs field: {files_with_sdgs}")
    logger.info(f"  Files needing fixes: {files_needing_fixes}")

    if dry_run:
        logger.info(f"\nDRY RUN: Would fix {files_needing_fixes} files")
    else:
        logger.info(f"  Files updated: {files_updated}")
        logger.info(f"\n✓ Successfully updated {files_updated} JSON files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix SDG separator issue in JSON metadata files"
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Path to data directory (e.g., /path/to/data/uneg/pdfs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )

    args = parser.parse_args()

    fix_sdg_separators_in_files(args.data_dir, dry_run=args.dry_run)
