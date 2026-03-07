#!/usr/bin/env python3
"""Compare old and new UNEG download folders.

Matches files by node_id extracted from filenames, then compares:
  - PDF presence, size, and byte-level identity
  - JSON metadata field-by-field differences
  - Error file presence and content
  - Duplicate detection (old data had multi-report duplicates)
  - Cross-year file duplication (same node_id in multiple year dirs)
  - Report variant patterns (e.g. "- Main Report", "- Report 2")

Usage:
    python scripts/maintenance/compare_downloads.py OLD NEW [--agency X] [--year Y]

Examples:
    python scripts/maintenance/compare_downloads.py data/uneg/pdfs data/pdfs \\
        --agency FAO --year 2025
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Extensions that count as a successful document download
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx"}


def extract_node_id(filename: str) -> str | None:
    """Extract node_id from filename like 'some_title_16741.pdf' -> '16741'."""
    stem = Path(filename).stem
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[1]
    return None


def md5_file(filepath: str) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5(usedforsecurity=False)
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(base_dir: str, agency: str | None = None, year: str | None = None):
    """Collect all files grouped by node_id.

    Returns dict: node_id -> {
        'pdfs': [(path, size, md5)],
        'jsons': [(path, data)],
        'errors': [(path, content)],
    }
    """
    nodes: dict[str, dict[str, list[Any]]] = defaultdict(
        lambda: {"pdfs": [], "docs": [], "jsons": [], "errors": []}
    )

    base = Path(base_dir)
    if not base.exists():
        print(f"ERROR: Directory does not exist: {base_dir}")
        sys.exit(1)

    # Walk agency/year subdirs
    for agency_dir in sorted(base.iterdir()):
        if not agency_dir.is_dir():
            continue
        if agency and agency_dir.name != agency:
            continue

        for year_dir in sorted(agency_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            if year and year_dir.name != year:
                continue

            for f in sorted(year_dir.iterdir()):
                if not f.is_file():
                    continue

                node_id = extract_node_id(f.name)
                if not node_id:
                    continue

                if f.suffix == ".pdf":
                    size = f.stat().st_size
                    md5 = md5_file(str(f))
                    nodes[node_id]["pdfs"].append((str(f), size, md5))
                elif f.suffix in (".doc", ".docx"):
                    size = f.stat().st_size
                    md5 = md5_file(str(f))
                    nodes[node_id]["docs"].append((str(f), size, md5))
                elif f.suffix == ".json":
                    try:
                        with open(f) as jf:
                            data = json.load(jf)
                        nodes[node_id]["jsons"].append((str(f), data))
                    except Exception as e:
                        nodes[node_id]["jsons"].append(
                            (str(f), {"_parse_error": str(e)})
                        )
                elif f.suffix == ".error":
                    try:
                        content = f.read_text()
                        nodes[node_id]["errors"].append((str(f), content))
                    except Exception as e:
                        nodes[node_id]["errors"].append((str(f), f"Read error: {e}"))

    return dict(nodes)


def collect_error_breakdown(
    base_dir: str, agency: str | None = None, year: str | None = None
) -> dict[tuple[str, str], dict]:
    """Lightweight pass: count documents vs errors per agency/year.

    Returns {(agency, year): {total, documents, errors, error_only}}.
    Skips md5 hashing — only checks file extensions.
    """
    # node_id -> {has_doc, has_error} per (agency, year)
    buckets: dict[tuple[str, str], dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"has_doc": False, "has_error": False})
    )

    base = Path(base_dir)
    if not base.exists():
        return {}

    for agency_dir in sorted(base.iterdir()):
        if not agency_dir.is_dir():
            continue
        if agency and agency_dir.name != agency:
            continue

        for year_dir in sorted(agency_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            if year and year_dir.name != year:
                continue

            key = (agency_dir.name, year_dir.name)

            for f in year_dir.iterdir():
                if not f.is_file():
                    continue
                node_id = extract_node_id(f.name)
                if not node_id:
                    continue

                if f.suffix in DOCUMENT_EXTENSIONS:
                    buckets[key][node_id]["has_doc"] = True
                elif f.suffix == ".error":
                    buckets[key][node_id]["has_error"] = True

    result = {}
    for key, nodes in buckets.items():
        total = len(nodes)
        documents = sum(1 for n in nodes.values() if n["has_doc"])
        errors = sum(1 for n in nodes.values() if n["has_error"])
        error_only = sum(
            1 for n in nodes.values() if n["has_error"] and not n["has_doc"]
        )
        result[key] = {
            "total": total,
            "documents": documents,
            "errors": errors,
            "error_only": error_only,
        }
    return result


# Regex to detect report variant suffixes like "- Main Report", "- Report 2"
REPORT_VARIANT_PATTERN = re.compile(
    r"_-_(?:main[_ ]?report|report[_ ]?\d+)", re.IGNORECASE
)


def detect_report_variants(
    base_dir: str, agency: str | None = None, year: str | None = None
) -> dict[str, list[str]]:
    """Find node_ids that have report variant filenames (Main Report, Report N).

    Returns {node_id: [list of variant suffixes found]}.
    """
    variants: dict[str, set[str]] = defaultdict(set)
    base = Path(base_dir)
    if not base.exists():
        return {}

    for agency_dir in sorted(base.iterdir()):
        if not agency_dir.is_dir():
            continue
        if agency and agency_dir.name != agency:
            continue
        for year_dir in sorted(agency_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            if year and year_dir.name != year:
                continue
            for f in year_dir.iterdir():
                if not f.is_file() or f.suffix != ".json":
                    continue
                m = REPORT_VARIANT_PATTERN.search(f.stem)
                if m:
                    node_id = extract_node_id(f.name)
                    if node_id:
                        # Normalize the variant label
                        variant = m.group(0).replace("_", " ").strip("- ").title()
                        variants[node_id].add(variant)

    return {nid: sorted(v) for nid, v in variants.items()}


def detect_cross_year_duplicates(
    base_dir: str, agency: str | None = None, year: str | None = None
) -> dict[str, list[str]]:
    """Find node_ids that appear in multiple year directories for the same agency.

    Returns {(agency, node_id): [list of years]}.
    """
    node_years: dict[tuple[str, str], set[str]] = defaultdict(set)
    base = Path(base_dir)
    if not base.exists():
        return {}

    for agency_dir in sorted(base.iterdir()):
        if not agency_dir.is_dir():
            continue
        if agency and agency_dir.name != agency:
            continue
        for year_dir in sorted(agency_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            if year and year_dir.name != year:
                continue
            for f in year_dir.iterdir():
                if not f.is_file() or f.suffix != ".json":
                    continue
                node_id = extract_node_id(f.name)
                if node_id:
                    node_years[(agency_dir.name, node_id)].add(year_dir.name)

    result: dict[str, list[str]] = {}
    for k, v in node_years.items():
        if len(v) > 1:
            key = f"{k[0]}:{k[1]}"
            result[key] = sorted(v)
    return result


# Fields to skip in JSON comparison (expected to differ)
SKIP_FIELDS = {"download_date", "filepath", "filename", "file_format"}


def compare_json(old_data: dict, new_data: dict) -> list[dict]:
    """Compare two JSON metadata dicts field-by-field.

    Returns list of {field, old, new} for fields that differ.
    """
    diffs = []
    all_keys = sorted(set(list(old_data.keys()) + list(new_data.keys())))

    for key in all_keys:
        if key in SKIP_FIELDS:
            continue
        old_val = old_data.get(key, "<missing>")
        new_val = new_data.get(key, "<missing>")
        # Normalize whitespace for comparison
        if isinstance(old_val, str) and isinstance(new_val, str):
            old_norm = " ".join(old_val.split())
            new_norm = " ".join(new_val.split())
            if old_norm == new_norm:
                continue
        elif old_val == new_val:
            continue
        diffs.append({"field": key, "old": old_val, "new": new_val})
    return diffs


def truncate(s, maxlen=100):
    """Truncate a string for display."""
    s = str(s)
    if len(s) <= maxlen:
        return s
    return s[:maxlen] + "..."


def main():
    parser = argparse.ArgumentParser(
        description="Compare old and new UNEG download folders"
    )
    parser.add_argument("old_dir", help="Path to old download directory")
    parser.add_argument("new_dir", help="Path to new download directory")
    parser.add_argument("--agency", help="Filter to specific agency (e.g. FAO)")
    parser.add_argument("--year", help="Filter to specific year (e.g. 2025)")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show all JSON diff details"
    )
    parser.add_argument("--json-output", help="Write structured results to JSON file")
    parser.add_argument(
        "--csv-output",
        help="Write error-rate breakdown by agency/year to CSV file",
    )
    args = parser.parse_args()

    print("Comparing downloads:")
    print(f"  OLD: {args.old_dir}")
    print(f"  NEW: {args.new_dir}")
    if args.agency:
        print(f"  Agency filter: {args.agency}")
    if args.year:
        print(f"  Year filter: {args.year}")
    print()

    old_nodes = collect_files(args.old_dir, args.agency, args.year)
    new_nodes = collect_files(args.new_dir, args.agency, args.year)

    all_node_ids = sorted(set(list(old_nodes.keys()) + list(new_nodes.keys())), key=int)

    print(f"Node IDs in OLD: {len(old_nodes)}")
    print(f"Node IDs in NEW: {len(new_nodes)}")
    print(f"Total unique node IDs: {len(all_node_ids)}")
    print()

    # --- Error rate comparison ---
    def error_rate_stats(nodes: dict) -> dict:
        """Compute download error rate for a set of nodes."""
        total = len(nodes)
        has_error = 0
        has_document = 0  # pdf, doc, or docx
        error_only = 0  # error with no successful document
        for nid, data in nodes.items():
            has_err = len(data["errors"]) > 0
            has_doc = len(data["pdfs"]) > 0 or len(data["docs"]) > 0
            if has_err:
                has_error += 1
            if has_doc:
                has_document += 1
            if has_err and not has_doc:
                error_only += 1
        return {
            "total": total,
            "has_error": has_error,
            "has_document": has_document,
            "error_only": error_only,
        }

    old_err = error_rate_stats(old_nodes)
    new_err = error_rate_stats(new_nodes)

    def pct(n, total):
        return f"{n / total * 100:.1f}%" if total else "N/A"

    print("=" * 70)
    print("ERROR RATE COMPARISON")
    print("=" * 70)
    print(f"{'':30s} {'OLD':>12s} {'NEW':>12s}")
    print(f"  {'Total nodes':<28s} {old_err['total']:>12,d} {new_err['total']:>12,d}")
    has_doc_old = old_err["has_document"]
    has_doc_new = new_err["has_document"]
    has_err_old = old_err["has_error"]
    has_err_new = new_err["has_error"]
    err_only_old = old_err["error_only"]
    err_only_new = new_err["error_only"]
    print(f"  {'Nodes with document':<28s} {has_doc_old:>12,d} {has_doc_new:>12,d}")
    print(f"  {'Nodes with error file':<28s} {has_err_old:>12,d} {has_err_new:>12,d}")
    print(
        f"  {'Error-only (no document)':<28s} {err_only_old:>12,d} {err_only_new:>12,d}"
    )
    print()
    old_rate = pct(old_err["error_only"], old_err["total"])
    new_rate = pct(new_err["error_only"], new_err["total"])
    print("  Error rate (error-only / total nodes):")
    print(f"    OLD: {old_err['error_only']:,} / {old_err['total']:,} = {old_rate}")
    print(f"    NEW: {new_err['error_only']:,} / {new_err['total']:,} = {new_rate}")
    if old_err["total"] and new_err["total"]:
        old_r = old_err["error_only"] / old_err["total"] * 100
        new_r = new_err["error_only"] / new_err["total"] * 100
        delta = new_r - old_r
        direction = "WORSE" if delta > 0 else "BETTER" if delta < 0 else "SAME"
        print(f"    Delta: {delta:+.1f}pp ({direction})")
    print()

    # Categorize nodes
    only_old = [n for n in all_node_ids if n in old_nodes and n not in new_nodes]
    only_new = [n for n in all_node_ids if n not in old_nodes and n in new_nodes]
    in_both = [n for n in all_node_ids if n in old_nodes and n in new_nodes]

    if only_old:
        print(f"=== NODES ONLY IN OLD ({len(only_old)}) ===")
        for nid in only_old:
            old = old_nodes[nid]
            pdfs = len(old["pdfs"])
            docs = len(old["docs"])
            errors = len(old["errors"])
            url = f"https://www.unevaluation.org/node/{nid}"
            print(f"  Node {nid}: {pdfs} PDFs, {docs} docs, {errors} errors  {url}")
        print()

    if only_new:
        print(f"=== NODES ONLY IN NEW ({len(only_new)}) ===")
        for nid in only_new:
            new = new_nodes[nid]
            pdfs = len(new["pdfs"])
            docs = len(new["docs"])
            errors = len(new["errors"])
            url = f"https://www.unevaluation.org/node/{nid}"
            print(f"  Node {nid}: {pdfs} PDFs, {docs} docs, {errors} errors  {url}")
        print()

    # Stats
    pdf_identical = 0
    pdf_different = 0
    pdf_old_only = 0
    pdf_new_only = 0
    json_identical = 0
    json_different = 0
    error_changes = 0
    old_duplicates = 0
    node_details = []

    print(f"=== COMPARING {len(in_both)} SHARED NODES ===")
    print()

    for nid in in_both:
        old = old_nodes[nid]
        new = new_nodes[nid]
        issues = []

        # --- PDF comparison ---
        old_pdfs = old["pdfs"]
        new_pdfs = new["pdfs"]

        if len(old_pdfs) > 1:
            old_duplicates += len(old_pdfs) - 1
            issues.append(f"OLD has {len(old_pdfs)} PDF copies (duplicates)")

        if old_pdfs and new_pdfs:
            # Compare first old PDF against new PDF (old may have duplicates)
            old_path, old_size, old_md5 = old_pdfs[0]
            new_path, new_size, new_md5 = new_pdfs[0]

            if old_md5 == new_md5:
                pdf_identical += 1
            else:
                pdf_different += 1
                size_diff = new_size - old_size
                sign = "+" if size_diff > 0 else ""
                issues.append(
                    f"PDF DIFFERS: old={old_size:,}B new={new_size:,}B ({sign}{size_diff:,}B)"
                )
        elif old_pdfs and not new_pdfs:
            pdf_old_only += 1
            issues.append("PDF MISSING in new (regression)")
        elif new_pdfs and not old_pdfs:
            pdf_new_only += 1
            issues.append("PDF NEW (not in old - improvement)")

        # --- Error comparison ---
        old_errors = old["errors"]
        new_errors = new["errors"]

        if old_errors and not new_errors:
            issues.append("Error RESOLVED: was error in old, success in new")
            error_changes += 1
        elif not old_errors and new_errors:
            error_content = new_errors[0][1][:200]
            issues.append(f"NEW ERROR (regression): {error_content}")
            error_changes += 1
        elif old_errors and new_errors:
            old_content = old_errors[0][1].strip()
            new_content = new_errors[0][1].strip()
            if old_content != new_content:
                issues.append("Error CHANGED")
                error_changes += 1

        # --- JSON comparison ---
        old_jsons = old["jsons"]
        new_jsons = new["jsons"]

        json_diffs = []
        if old_jsons and new_jsons:
            # Compare first JSON from each (old may have duplicates for multi-report)
            old_data = old_jsons[0][1]
            new_data = new_jsons[0][1]
            json_diffs = compare_json(old_data, new_data)

            if json_diffs:
                json_different += 1
            else:
                json_identical += 1
        elif old_jsons and not new_jsons:
            issues.append("JSON MISSING in new")
        elif new_jsons and not old_jsons:
            issues.append("JSON NEW (not in old)")

        # Categorize JSON diffs
        metadata_richer = []
        metadata_lost = []
        metadata_changed = []

        for d in json_diffs:
            old_empty = (
                not d["old"] or d["old"] == "<missing>" or str(d["old"]).strip() == ""
            )
            new_empty = (
                not d["new"] or d["new"] == "<missing>" or str(d["new"]).strip() == ""
            )

            if old_empty and not new_empty:
                metadata_richer.append(d)
            elif not old_empty and new_empty:
                metadata_lost.append(d)
            else:
                metadata_changed.append(d)

        if metadata_lost:
            fields = ", ".join(d["field"] for d in metadata_lost)
            issues.append(f"METADATA LOST: {fields}")
        if metadata_richer:
            fields = ", ".join(d["field"] for d in metadata_richer)
            issues.append(f"Metadata richer: {fields}")
        if metadata_changed:
            fields = ", ".join(d["field"] for d in metadata_changed)
            issues.append(f"Metadata changed: {fields}")

        detail = {
            "node_id": nid,
            "url": f"https://www.unevaluation.org/node/{nid}",
            "issues": issues,
            "json_diffs": json_diffs,
            "old_pdf_count": len(old_pdfs),
            "new_pdf_count": len(new_pdfs),
            "old_error_count": len(old_errors),
            "new_error_count": len(new_errors),
        }
        node_details.append(detail)

        if issues:
            print(f"  Node {nid}  https://www.unevaluation.org/node/{nid}")
            for issue in issues:
                print(f"    - {issue}")
            if args.verbose and json_diffs:
                for d in json_diffs:
                    print(f"      [{d['field']}]")
                    print(f"        OLD: {truncate(d['old'], 150)}")
                    print(f"        NEW: {truncate(d['new'], 150)}")
            print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total nodes compared: {len(in_both)}")
    print(f"  Nodes only in OLD:    {len(only_old)}")
    print(f"  Nodes only in NEW:    {len(only_new)}")
    print()
    print(f"  PDFs identical:       {pdf_identical}")
    print(f"  PDFs different:       {pdf_different}")
    print(
        f"  PDFs only in old:     {pdf_old_only}  {'⚠ REGRESSION' if pdf_old_only else ''}"
    )
    print(
        f"  PDFs only in new:     {pdf_new_only}  {'✓ improvement' if pdf_new_only else ''}"
    )
    print(f"  Old duplicate PDFs:   {old_duplicates}  (eliminated in new)")
    print()
    print(f"  JSON identical:       {json_identical}")
    print(f"  JSON different:       {json_different}")
    print()
    print(f"  Error status changes: {error_changes}")
    print()
    print(f"  Error rate OLD:       {pct(old_err['error_only'], old_err['total'])}")
    print(f"  Error rate NEW:       {pct(new_err['error_only'], new_err['total'])}")

    # Flag regressions
    regressions = [
        d for d in node_details if any("regression" in i.lower() for i in d["issues"])
    ]
    if regressions:
        print()
        print("⚠  REGRESSIONS (action required):")
        for d in regressions:
            reg_issues = [i for i in d["issues"] if "regression" in i.lower()]
            print(f"  Node {d['node_id']}  {d['url']}")
            for i in reg_issues:
                print(f"    - {i}")

    # Flag metadata loss
    losses = [d for d in node_details if any("METADATA LOST" in i for i in d["issues"])]
    if losses:
        print()
        print("⚠  METADATA LOSSES:")
        for d in losses:
            loss_issues = [i for i in d["issues"] if "METADATA LOST" in i]
            print(f"  Node {d['node_id']}  {d['url']}")
            for i in loss_issues:
                print(f"    - {i}")

    # --- DB update estimate ---
    # Count new-only nodes that have at least one document (need full ingestion)
    new_with_doc = sum(
        1
        for nid in only_new
        if len(new_nodes[nid]["pdfs"]) > 0 or len(new_nodes[nid]["docs"]) > 0
    )
    new_error_only = len(only_new) - new_with_doc

    # Shared nodes: metadata-only = identical PDF; re-ingest = different PDF
    # pdf_old_only = had PDF in old, error/missing in new (regression - keep old)
    # pdf_new_only = no PDF in old, has PDF in new (improvement - need ingestion)

    print()
    print("=" * 70)
    print("DB UPDATE ESTIMATE")
    print("=" * 70)
    print(
        f"  New files to ingest:       {new_with_doc + pdf_new_only:>6d}"
        f"  ({new_with_doc} new nodes + {pdf_new_only} newly resolved)"
    )
    print(
        f"  Metadata-only updates:     {pdf_identical:>6d}"
        f"  (identical PDF, updated metadata)"
    )
    print(f"  Re-ingest (PDF changed):   {pdf_different:>6d}")
    print(f"  Delete from DB:            {len(only_old):>6d}" f"  (nodes only in old)")
    print(
        f"  Regressions (had PDF, now error): {pdf_old_only:>4d}"
        f"  (keep old PDF, update metadata)"
    )
    print(
        f"  New error-only (skip):     {new_error_only:>6d}"
        f"  (no document to ingest)"
    )
    print()

    # --- Error rate breakdown by agency/year ---
    old_breakdown = collect_error_breakdown(args.old_dir, args.agency, args.year)
    new_breakdown = collect_error_breakdown(args.new_dir, args.agency, args.year)
    all_keys = sorted(set(list(old_breakdown.keys()) + list(new_breakdown.keys())))

    if all_keys:
        empty = {"total": 0, "documents": 0, "errors": 0, "error_only": 0}

        print()
        print("=" * 70)
        print("ERROR RATE BY AGENCY / YEAR")
        print("=" * 70)
        print(
            f"  {'Agency':<12s} {'Year':<6s}"
            f"  {'Old Tot':>7s} {'Old Err':>7s} {'Old %':>6s}"
            f"  {'New Tot':>7s} {'New Err':>7s} {'New %':>6s}"
            f"  {'Delta':>7s}"
        )
        print("  " + "-" * 66)

        for ag, yr in all_keys:
            o = old_breakdown.get((ag, yr), empty)
            n = new_breakdown.get((ag, yr), empty)
            o_rate = o["error_only"] / o["total"] * 100 if o["total"] else 0
            n_rate = n["error_only"] / n["total"] * 100 if n["total"] else 0
            delta = n_rate - o_rate
            print(
                f"  {ag:<12s} {yr:<6s}"
                f"  {o['total']:>7d} {o['error_only']:>7d} {o_rate:>5.1f}%"
                f"  {n['total']:>7d} {n['error_only']:>7d} {n_rate:>5.1f}%"
                f"  {delta:>+6.1f}pp"
            )
        print()

    # --- Report variant detection ---
    print("=" * 70)
    print("REPORT VARIANT PATTERNS (e.g. 'Main Report', 'Report 2')")
    print("=" * 70)
    old_variants = detect_report_variants(args.old_dir, args.agency, args.year)
    new_variants = detect_report_variants(args.new_dir, args.agency, args.year)
    print(f"  OLD: {len(old_variants)} node_ids with report variants")
    print(f"  NEW: {len(new_variants)} node_ids with report variants")
    if new_variants:
        # Summarize variant types
        all_variant_labels: dict[str, int] = defaultdict(int)
        for _nid, labels in new_variants.items():
            for label in labels:
                all_variant_labels[label] += 1
        print()
        print("  NEW variant types:")
        for label, count in sorted(all_variant_labels.items(), key=lambda x: -x[1]):
            print(f"    {label}: {count} node_ids")
        if args.verbose:
            print()
            for nid, labels in sorted(new_variants.items(), key=lambda x: int(x[0])):
                print(f"    Node {nid}: {', '.join(labels)}")
    else:
        print("  NEW: No report variant patterns found ✓")
    print()

    # --- Cross-year duplication detection ---
    print("=" * 70)
    print("CROSS-YEAR FILE DUPLICATION (same node_id in multiple year dirs)")
    print("=" * 70)
    old_cross_year = detect_cross_year_duplicates(args.old_dir, args.agency, args.year)
    new_cross_year = detect_cross_year_duplicates(args.new_dir, args.agency, args.year)
    print(f"  OLD: {len(old_cross_year)} node_ids duplicated across years")
    print(f"  NEW: {len(new_cross_year)} node_ids duplicated across years")
    if new_cross_year:
        # Summarize by agency
        agency_counts: dict[str, int] = defaultdict(int)
        for (ag, _nid), _years in new_cross_year.items():
            agency_counts[ag] += 1
        print()
        print("  NEW cross-year duplicates by agency:")
        for ag, count in sorted(agency_counts.items(), key=lambda x: -x[1]):
            # Show sample of year spread
            sample_key = next(k for k in new_cross_year if k[0] == ag)
            sample_years = new_cross_year[sample_key]
            print(
                f"    {ag}: {count} node_ids (e.g. years: {', '.join(sample_years[:5])})"
            )

        print()
        print("  ⚠  Cross-year duplication inflates per-year counts in the breakdown!")
        print("     These node_ids are counted once per year directory they appear in.")
    print()

    # --- CSV output ---
    if args.csv_output:
        empty = {"total": 0, "documents": 0, "errors": 0, "error_only": 0}
        with open(args.csv_output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "agency",
                    "year",
                    "old_total",
                    "old_documents",
                    "old_errors",
                    "old_error_only",
                    "old_error_rate",
                    "new_total",
                    "new_documents",
                    "new_errors",
                    "new_error_only",
                    "new_error_rate",
                    "delta_pp",
                    "delta_reports",
                    "delta_errors",
                ]
            )
            for ag, yr in all_keys:
                o = old_breakdown.get((ag, yr), empty)
                n = new_breakdown.get((ag, yr), empty)
                o_rate = o["error_only"] / o["total"] * 100 if o["total"] else 0
                n_rate = n["error_only"] / n["total"] * 100 if n["total"] else 0
                delta = n_rate - o_rate
                delta_reports = n["documents"] - o["documents"]
                delta_errors = n["error_only"] - o["error_only"]
                writer.writerow(
                    [
                        ag,
                        yr,
                        o["total"],
                        o["documents"],
                        o["errors"],
                        o["error_only"],
                        round(o_rate, 1),
                        n["total"],
                        n["documents"],
                        n["errors"],
                        n["error_only"],
                        round(n_rate, 1),
                        round(delta, 1),
                        delta_reports,
                        delta_errors,
                    ]
                )
        print(f"CSV breakdown written to: {args.csv_output}")

    # Optional JSON output
    if args.json_output:
        output = {
            "old_dir": args.old_dir,
            "new_dir": args.new_dir,
            "agency": args.agency,
            "year": args.year,
            "summary": {
                "total_nodes": len(in_both),
                "only_old": len(only_old),
                "only_new": len(only_new),
                "pdf_identical": pdf_identical,
                "pdf_different": pdf_different,
                "pdf_old_only": pdf_old_only,
                "pdf_new_only": pdf_new_only,
                "old_duplicates": old_duplicates,
                "json_identical": json_identical,
                "json_different": json_different,
                "error_changes": error_changes,
                "error_rate_old": old_err,
                "error_rate_new": new_err,
            },
            "only_old_nodes": only_old,
            "only_new_nodes": only_new,
            "node_details": node_details,
        }
        with open(args.json_output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nDetailed JSON written to: {args.json_output}")

    print()


if __name__ == "__main__":
    main()
