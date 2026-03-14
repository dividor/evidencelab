#!/usr/bin/env python3
"""Backfill-fix existing World Bank metadata JSON files.

For each .json file under the worldbank data directory:
1. Copy the original to .backup.json
2. Apply normalize_metadata (flatten nested dicts, comma→semicolon)
3. Overwrite the .json with the corrected version

Usage:
    python scripts/fix_worldbank_metadata.py [--data-dir PATH] [--dry-run]
"""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

# Add project root so we can import the downloader
_project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_project_root))
sys.path.insert(
    0,
    str(_project_root / "pipeline" / "integration" / "evidencelab-ai-integration"),
)

from worldbank.download import WorldBankDownloader  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def fix_file(json_path: Path, dry_run: bool = False) -> bool:
    """Backup and normalize one metadata file. Returns True if changed."""
    with open(json_path, "r", encoding="utf-8") as f:
        original = json.load(f)

    normalized = json.loads(json.dumps(original))  # deep copy
    WorldBankDownloader.normalize_metadata(normalized)

    if normalized == original:
        return False

    backup_path = json_path.with_suffix(".backup.json")
    if dry_run:
        logger.info("Would fix: %s", json_path)
        return True

    # Backup original
    if not backup_path.exists():
        shutil.copy2(json_path, backup_path)

    # Write corrected
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=str,
        default="/Users/matthewharris/Data/evidencelab/data/worldbank",
        help="Root directory containing worldbank metadata JSON files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying files",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        logger.error("Data directory not found: %s", data_dir)
        sys.exit(1)

    json_files = sorted(data_dir.rglob("*.json"))
    # Exclude backup files
    json_files = [f for f in json_files if not f.name.endswith(".backup.json")]

    logger.info("Found %d JSON files in %s", len(json_files), data_dir)

    changed = 0
    errors = 0
    for i, path in enumerate(json_files, 1):
        try:
            if fix_file(path, dry_run=args.dry_run):
                changed += 1
        except Exception:
            logger.exception("Error processing %s", path)
            errors += 1

        if i % 1000 == 0:
            logger.info("Progress: %d / %d (changed: %d)", i, len(json_files), changed)

    action = "Would fix" if args.dry_run else "Fixed"
    logger.info(
        "Done. %s %d / %d files (%d errors).",
        action,
        changed,
        len(json_files),
        errors,
    )


if __name__ == "__main__":
    main()
