#!/usr/bin/env python3
"""Update UNEG data tree: deduplicate, align metadata, and stage new content.

This script prepares the data/uneg/pdfs/ tree so that the scanner can detect
changes and new documents without re-ingesting unchanged content.

Operations performed (in order):
  1. Remove identical-duplicate PDFs (old download created two copies per node)
  2. Align metadata from new download where PDF checksums match
  3. Update metadata-only for non-duplicate nodes with identical PDFs
  4. Update metadata for regression nodes (old PDF kept, new JSON applied)
  5. Copy brand-new nodes from uneg-new into the tree
  6. Copy newly-available PDFs (previously errored) into the tree
  7. Replace reassigned nodes (3 nodes where node_id maps to different doc)

Usage:
    # Dry run (default) — reports what would change
    python scripts/maintenance/update_uneg_data.py

    # Execute changes
    python scripts/maintenance/update_uneg_data.py --wet-run

    # Write structured report to JSON
    python scripts/maintenance/update_uneg_data.py --json-output report.json
"""

import argparse
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# --- Helpers ----------------------------------------------------------------


def extract_node_id(filename: str) -> str | None:
    """Extract node_id from filename like 'some_title_16741.pdf' -> '16741'."""
    stem = Path(filename).stem
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[1]
    return None


def md5_file(filepath: Path) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5(usedforsecurity=False)
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_node_files(base_dir: Path) -> dict[str, dict]:
    """Collect all files grouped by node_id.

    Returns dict: node_id -> {
        'pdfs': [(path, md5)],
        'jsons': [(path, data)],
        'errors': [path],
    }
    """
    nodes: dict[str, dict] = defaultdict(
        lambda: {"pdfs": [], "jsons": [], "errors": []}
    )

    if not base_dir.exists():
        print(f"ERROR: Directory does not exist: {base_dir}")
        sys.exit(1)

    for agency_dir in sorted(base_dir.iterdir()):
        if not agency_dir.is_dir():
            continue
        for year_dir in sorted(agency_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            for f in sorted(year_dir.iterdir()):
                if not f.is_file():
                    continue
                node_id = extract_node_id(f.name)
                if not node_id:
                    continue
                if f.suffix == ".pdf":
                    nodes[node_id]["pdfs"].append((f, md5_file(f)))
                elif f.suffix == ".json":
                    try:
                        data = json.loads(f.read_text())
                        nodes[node_id]["jsons"].append((f, data))
                    except Exception:
                        nodes[node_id]["jsons"].append((f, None))
                elif f.suffix == ".error":
                    nodes[node_id]["errors"].append(f)

    return dict(nodes)


# --- Actions ----------------------------------------------------------------


class ActionLog:
    """Track actions to perform/report."""

    def __init__(self, wet_run: bool = False):
        self.wet_run = wet_run
        self.actions: list[dict] = []
        self.stats: dict[str, int] = defaultdict(int)

    def delete_file(self, path: Path, reason: str, category: str):
        self.actions.append(
            {
                "action": "delete",
                "path": str(path),
                "reason": reason,
                "category": category,
            }
        )
        self.stats[f"delete:{category}"] += 1
        if self.wet_run:
            path.unlink()

    def copy_file(self, src: Path, dst: Path, reason: str, category: str):
        self.actions.append(
            {
                "action": "copy",
                "src": str(src),
                "dst": str(dst),
                "reason": reason,
                "category": category,
            }
        )
        self.stats[f"copy:{category}"] += 1
        if self.wet_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def replace_json(self, old_path: Path, new_path: Path, reason: str, category: str):
        self.actions.append(
            {
                "action": "replace_json",
                "old": str(old_path),
                "new_src": str(new_path),
                "reason": reason,
                "category": category,
            }
        )
        self.stats[f"replace_json:{category}"] += 1
        if self.wet_run:
            shutil.copy2(new_path, old_path)

    def summary(self) -> dict:
        return dict(self.stats)


# --- Main logic -------------------------------------------------------------

REASSIGNED_NODES = {"316", "317", "16770"}


def run(old_dir: Path, new_dir: Path, log: ActionLog):
    print("Scanning old data...")
    old_nodes = collect_node_files(old_dir)
    print(f"  {len(old_nodes)} nodes found in old data")

    print("Scanning new data...")
    new_nodes = collect_node_files(new_dir)
    print(f"  {len(new_nodes)} nodes found in new data")
    print()

    all_node_ids = sorted(set(list(old_nodes.keys()) + list(new_nodes.keys())), key=int)

    only_old_ids = [n for n in all_node_ids if n in old_nodes and n not in new_nodes]
    only_new_ids = [n for n in all_node_ids if n not in old_nodes and n in new_nodes]
    shared_ids = [n for n in all_node_ids if n in old_nodes and n in new_nodes]

    # --- Step 7: Reassigned nodes -------------------------------------------
    print("=== STEP 1: Reassigned nodes ===")
    for nid in REASSIGNED_NODES:
        if nid not in old_nodes or nid not in new_nodes:
            continue
        old = old_nodes[nid]
        new = new_nodes[nid]
        # Delete all old files
        for path, _ in old["pdfs"]:
            log.delete_file(path, f"reassigned node {nid}", "reassigned")
        for path, _ in old["jsons"]:
            log.delete_file(path, f"reassigned node {nid}", "reassigned")
        for path in old["errors"]:
            log.delete_file(path, f"reassigned node {nid}", "reassigned")
        # Copy all new files
        for path, _ in new["pdfs"]:
            dst = old_dir / path.relative_to(new_dir)
            log.copy_file(path, dst, f"reassigned node {nid}", "reassigned")
        for path, _ in new["jsons"]:
            dst = old_dir / path.relative_to(new_dir)
            log.copy_file(path, dst, f"reassigned node {nid}", "reassigned")
        for path in new["errors"]:
            dst = old_dir / path.relative_to(new_dir)
            log.copy_file(path, dst, f"reassigned node {nid}", "reassigned")
    print(
        f"  {log.stats.get('delete:reassigned', 0)} files to delete, "
        f"{log.stats.get('copy:reassigned', 0)} files to copy"
    )
    print()

    # --- Steps 1-2: Identical duplicates ------------------------------------
    print("=== STEP 2: Remove identical duplicates & align metadata ===")
    dup_identical = 0
    dup_with_new_meta = 0
    dup_without_new_meta = 0
    dup_multidoc_preserved = 0
    dup_changed_pdf = 0

    for nid in shared_ids:
        if nid in REASSIGNED_NODES:
            continue
        old = old_nodes[nid]
        old_pdfs = old["pdfs"]
        if len(old_pdfs) < 2:
            continue

        # Check if identical (all same md5)
        unique_checksums = set(md5 for _, md5 in old_pdfs)
        if len(unique_checksums) > 1:
            # Multi-doc node — preserve all
            dup_multidoc_preserved += 1
            continue

        dup_identical += 1
        old_md5 = old_pdfs[0][1]

        # Check if new download has a matching PDF
        new = new_nodes[nid]
        new_pdfs = new["pdfs"]
        new_md5 = new_pdfs[0][1] if new_pdfs else None

        # Keep first old PDF, delete the rest
        keep_path = old_pdfs[0][0]
        keep_json = old["jsons"][0][0] if old["jsons"] else None

        for path, _ in old_pdfs[1:]:
            log.delete_file(path, f"identical dupe of {keep_path.name}", "dupe_pdf")
        # Delete extra JSONs too (keep first)
        for path, _ in old["jsons"][1:]:
            log.delete_file(path, f"dupe JSON for node {nid}", "dupe_json")

        if new_md5 == old_md5 and new["jsons"] and keep_json:
            # Checksum match — align metadata from new download
            dup_with_new_meta += 1
            new_json_path = new["jsons"][0][0]
            log.replace_json(
                keep_json,
                new_json_path,
                f"align metadata for node {nid}",
                "dupe_align_meta",
            )
        elif new_md5 and new_md5 != old_md5:
            dup_changed_pdf += 1
        else:
            dup_without_new_meta += 1

    # Also handle identical dupes in old-only nodes
    for nid in only_old_ids:
        old = old_nodes[nid]
        old_pdfs = old["pdfs"]
        if len(old_pdfs) < 2:
            continue
        unique_checksums = set(md5 for _, md5 in old_pdfs)
        if len(unique_checksums) > 1:
            dup_multidoc_preserved += 1
            continue
        dup_identical += 1
        dup_without_new_meta += 1
        keep_path = old_pdfs[0][0]
        for path, _ in old_pdfs[1:]:
            log.delete_file(path, f"identical dupe of {keep_path.name}", "dupe_pdf")
        for path, _ in old["jsons"][1:]:
            log.delete_file(path, f"dupe JSON for node {nid}", "dupe_json")

    print(f"  Identical-dupe nodes:        {dup_identical}")
    print(f"    With new metadata aligned: {dup_with_new_meta}")
    print(f"    Without new metadata:      {dup_without_new_meta}")
    print(f"    PDF changed in new (flag): {dup_changed_pdf}")
    print(f"  Multi-doc nodes preserved:   {dup_multidoc_preserved}")
    print()

    # --- Step 3: Metadata-only update for single-PDF nodes ------------------
    print("=== STEP 3: Metadata-only update (identical PDF, single copy) ===")
    meta_only_updated = 0

    for nid in shared_ids:
        if nid in REASSIGNED_NODES:
            continue
        old = old_nodes[nid]
        new = new_nodes[nid]
        old_pdfs = old["pdfs"]
        new_pdfs = new["pdfs"]

        # Skip dupes (handled above) and multi-doc
        if len(old_pdfs) != 1:
            continue
        if not new_pdfs:
            continue

        old_md5 = old_pdfs[0][1]
        new_md5 = new_pdfs[0][1]

        if old_md5 == new_md5 and old["jsons"] and new["jsons"]:
            # Same PDF, update metadata
            old_json_path = old["jsons"][0][0]
            new_json_path = new["jsons"][0][0]
            # Check if JSON actually differs
            old_json_data = old["jsons"][0][1]
            new_json_data = new["jsons"][0][1]
            if old_json_data != new_json_data:
                log.replace_json(
                    old_json_path,
                    new_json_path,
                    f"metadata update for node {nid}",
                    "meta_only",
                )
                meta_only_updated += 1

    print(f"  Nodes with metadata updated: {meta_only_updated}")
    print()

    # --- Step 4: Regression nodes — update metadata, keep old PDF -----------
    print("=== STEP 4: Regression nodes (keep old PDF, update metadata) ===")
    regression_meta_updated = 0
    regression_no_new_meta = 0

    for nid in shared_ids:
        if nid in REASSIGNED_NODES:
            continue
        old = old_nodes[nid]
        new = new_nodes[nid]
        old_pdfs = old["pdfs"]
        new_pdfs = new["pdfs"]

        if len(old_pdfs) != 1:
            continue
        if new_pdfs:
            continue  # Not a regression — new has PDF

        # Old has PDF, new doesn't — regression
        if old["jsons"] and new["jsons"]:
            old_json_data = old["jsons"][0][1]
            new_json_data = new["jsons"][0][1]
            if old_json_data != new_json_data:
                log.replace_json(
                    old["jsons"][0][0],
                    new["jsons"][0][0],
                    f"regression meta update for node {nid}",
                    "regression_meta",
                )
                regression_meta_updated += 1
            else:
                regression_no_new_meta += 1
        else:
            regression_no_new_meta += 1

    print(f"  Regression nodes with metadata updated: {regression_meta_updated}")
    print(f"  Regression nodes unchanged:             {regression_no_new_meta}")
    print()

    # --- Step 5: Brand new nodes --------------------------------------------
    print("=== STEP 5: Brand new nodes (copy from new tree) ===")
    new_nodes_copied = 0
    new_nodes_error_only = 0

    for nid in only_new_ids:
        new = new_nodes[nid]
        has_pdf = len(new["pdfs"]) > 0

        if not has_pdf and not new["jsons"]:
            continue  # Nothing useful

        if not has_pdf:
            new_nodes_error_only += 1
            # Still copy the JSON + error so scanner tracks it
            for path, _ in new["jsons"]:
                dst = old_dir / path.relative_to(new_dir)
                log.copy_file(path, dst, f"new node {nid} metadata", "new_node")
            for path in new["errors"]:
                dst = old_dir / path.relative_to(new_dir)
                log.copy_file(path, dst, f"new node {nid} error", "new_node")
            continue

        new_nodes_copied += 1
        # Copy all files for this node
        for path, _ in new["pdfs"]:
            dst = old_dir / path.relative_to(new_dir)
            log.copy_file(path, dst, f"new node {nid} PDF", "new_node_pdf")
        for path, _ in new["jsons"]:
            dst = old_dir / path.relative_to(new_dir)
            log.copy_file(path, dst, f"new node {nid} metadata", "new_node_json")
        for path in new["errors"]:
            dst = old_dir / path.relative_to(new_dir)
            log.copy_file(path, dst, f"new node {nid} error", "new_node_error")

    print(f"  New nodes with PDFs copied:  {new_nodes_copied}")
    print(f"  New nodes (error only):      {new_nodes_error_only}")
    print()

    # --- Step 6: Newly available PDFs (was error, now has PDF) ---------------
    print("=== STEP 6: Newly available PDFs (previously errored) ===")
    newly_available = 0

    for nid in shared_ids:
        if nid in REASSIGNED_NODES:
            continue
        old = old_nodes[nid]
        new = new_nodes[nid]

        # Old had no PDF, new has PDF
        if old["pdfs"] or not new["pdfs"]:
            continue

        newly_available += 1
        # Copy new PDF into old tree
        for path, _ in new["pdfs"]:
            dst = old_dir / path.relative_to(new_dir)
            log.copy_file(
                path, dst, f"newly available PDF for node {nid}", "newly_available_pdf"
            )
        # Replace JSON with new version
        if old["jsons"] and new["jsons"]:
            log.replace_json(
                old["jsons"][0][0],
                new["jsons"][0][0],
                f"newly available meta for node {nid}",
                "newly_available_meta",
            )
        elif new["jsons"]:
            for path, _ in new["jsons"]:
                dst = old_dir / path.relative_to(new_dir)
                log.copy_file(
                    path,
                    dst,
                    f"newly available meta for node {nid}",
                    "newly_available_meta",
                )
        # Remove old error file if exists
        for path in old["errors"]:
            log.delete_file(path, f"error resolved for node {nid}", "resolved_error")

    print(f"  Newly available PDFs: {newly_available}")
    print()

    # --- Step 6b: PDFs with changed content (105 from report) ---------------
    print("=== STEP 7: PDFs with changed content ===")
    pdf_changed = 0

    for nid in shared_ids:
        if nid in REASSIGNED_NODES:
            continue
        old = old_nodes[nid]
        new = new_nodes[nid]

        if len(old["pdfs"]) != 1 or not new["pdfs"]:
            continue

        old_md5 = old["pdfs"][0][1]
        new_md5 = new["pdfs"][0][1]

        if old_md5 != new_md5:
            pdf_changed += 1
            # Replace PDF with new version
            old_pdf_path = old["pdfs"][0][0]
            new_pdf_path = new["pdfs"][0][0]
            log.copy_file(
                new_pdf_path, old_pdf_path, f"updated PDF for node {nid}", "changed_pdf"
            )
            # Replace JSON
            if old["jsons"] and new["jsons"]:
                log.replace_json(
                    old["jsons"][0][0],
                    new["jsons"][0][0],
                    f"updated meta for changed PDF node {nid}",
                    "changed_pdf_meta",
                )

    print(f"  PDFs with changed content replaced: {pdf_changed}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Update UNEG data tree: deduplicate, align metadata, stage new content"
    )
    parser.add_argument(
        "--old-dir",
        default="data/uneg/pdfs",
        help="Path to current data tree (default: data/uneg/pdfs)",
    )
    parser.add_argument(
        "--new-dir",
        default="data/uneg-new",
        help="Path to new download tree (default: data/uneg-new)",
    )
    parser.add_argument(
        "--wet-run",
        action="store_true",
        help="Actually execute changes (default is dry-run)",
    )
    parser.add_argument(
        "--json-output", help="Write structured action log to JSON file"
    )
    args = parser.parse_args()

    mode = "WET RUN" if args.wet_run else "DRY RUN"
    print(f"{'=' * 70}")
    print(f"  UNEG Data Update — {mode}")
    print(f"{'=' * 70}")
    print(f"  Old tree: {args.old_dir}")
    print(f"  New tree: {args.new_dir}")
    print()

    log = ActionLog(wet_run=args.wet_run)
    run(Path(args.old_dir), Path(args.new_dir), log)

    # --- Final summary ------------------------------------------------------
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for key, count in sorted(log.summary().items()):
        print(f"  {key}: {count}")
    print()
    total_actions = len(log.actions)
    print(f"  Total actions: {total_actions}")
    if not args.wet_run:
        print("\n  *** DRY RUN — no changes made. Use --wet-run to execute. ***")
    else:
        print(f"\n  *** WET RUN — {total_actions} actions executed. ***")
    print()

    if args.json_output:
        output = {
            "mode": mode,
            "old_dir": args.old_dir,
            "new_dir": args.new_dir,
            "summary": log.summary(),
            "total_actions": total_actions,
            "actions": log.actions,
        }
        with open(args.json_output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Action log written to: {args.json_output}")


if __name__ == "__main__":
    main()
