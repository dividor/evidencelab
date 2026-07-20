#!/usr/bin/env python3
"""
Check that every section inside a document's main-body page range is tagged with
a section type that is *included* by default in Search / Content settings.

The validation logic lives in ``pipeline.validation.section_inclusion`` (shared
with the backend TOC validator). This script is the standalone/offline runner: it
reads documents from the Postgres sidecar, evaluates each one, writes an xlsx
report and prints a summary. See this directory's README for the full rationale.

Usage
-----
    # Check all documents in a data source
    python tests/evaluation/section_inclusion/check_included_section_types.py --data-source wfp

    # Check a sample of N documents
    python tests/evaluation/section_inclusion/check_included_section_types.py --records 20

    # Check a single document by doc id
    python tests/evaluation/section_inclusion/check_included_section_types.py --file-id <id>

    # Custom output path
    python tests/evaluation/section_inclusion/check_included_section_types.py --output results.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

from pipeline.validation.section_inclusion import (  # noqa: E402
    describe_excluded_sections,
    evaluate_document,
    get_document_title,
    get_intro_range_field,
)

# Only report on documents that finished indexing.
ALLOWED_STATUSES = {"indexed", "tagged"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Flag sections in the main-body page range that are tagged with a "
            "section type excluded from Search by default."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--records",
        type=int,
        default=None,
        help="Number of documents to process (default: all)",
    )
    group.add_argument(
        "--file-id",
        type=str,
        help="Process a single document by doc id",
    )
    parser.add_argument(
        "--data-source",
        type=str,
        default="wfp",
        help="Data source / table suffix (default: wfp)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(PROJECT_ROOT / "logs" / "section_inclusion_eval.xlsx"),
        help="Output Excel (.xlsx) file path",
    )
    return parser.parse_args()


def select_documents(
    docs: List[Dict[str, Any]], limit: Optional[int], file_id: Optional[str]
) -> List[Dict[str, Any]]:
    """Filter fetched docs down to the ones this run should evaluate."""
    if file_id:
        selected = [doc for doc in docs if str(doc.get("id")) == str(file_id)]
        if not selected:
            raise ValueError(f"Document {file_id} not found")
        return selected

    eligible = [doc for doc in docs if doc.get("sys_status") in ALLOWED_STATUSES]
    return eligible[:limit] if limit else eligible


def build_report_row(doc: Dict[str, Any], data_source: str) -> Dict[str, Any]:
    """Evaluate one doc and flatten the result into a report row."""
    result = evaluate_document(doc)
    return {
        "doc_id": str(doc.get("id")),
        "title": get_document_title(doc),
        "data_source": data_source,
        "metadata_range": str(get_intro_range_field(doc)),
        "range_start": result["range_start"],
        "range_end": result["range_end"],
        "sections_in_range": result["sections_in_range"],
        "num_excluded": result["num_excluded"],
        "excluded_section_types": ", ".join(result["excluded_section_types"]),
        "excluded_details": describe_excluded_sections(result["excluded_sections"]),
        "status": result["status"],
        "reasons": ", ".join(result["reasons"]),
    }


REPORT_HEADERS = [
    "doc_id",
    "title",
    "data_source",
    "metadata_range",
    "range_start",
    "range_end",
    "sections_in_range",
    "num_excluded",
    "excluded_section_types",
    "excluded_details",
    "status",
    "reasons",
]


def _create_workbook():
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Section Inclusion"
    ws.append(REPORT_HEADERS)
    header_fill = PatternFill(
        start_color="DCE6F1", end_color="DCE6F1", fill_type="solid"
    )
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    return wb, ws


def _print_summary(counts: Dict[str, int], excluded_tally: Dict[str, int]) -> None:
    total = sum(counts.values())
    print("\n" + "=" * 60)
    print(f"Documents processed : {total}")
    print(f"  pass    : {counts['pass']}")
    print(f"  fail    : {counts['fail']}  (body content excluded by default)")
    print(f"  skipped : {counts['skipped']}  (no range / no classified TOC)")
    if excluded_tally:
        print("\nExcluded section types found inside body ranges:")
        print("(documents affected, per section type)")
        for label, count in sorted(excluded_tally.items(), key=lambda kv: -kv[1]):
            print(f"  {label:<20} {count}")
    print("=" * 60)


def _tally_excluded(row: Dict[str, Any], excluded_tally: Dict[str, int]) -> None:
    for label in row["excluded_section_types"].split(", "):
        if label:
            excluded_tally[label] = excluded_tally.get(label, 0) + 1


def main() -> None:
    from pipeline.db import PostgresClient

    args = parse_args()
    pg = PostgresClient(args.data_source)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb, ws = _create_workbook()

    counts = {"pass": 0, "fail": 0, "skipped": 0}
    excluded_tally: Dict[str, int] = {}

    for doc in select_documents(pg.fetch_all_docs(), args.records, args.file_id):
        row = build_report_row(doc, args.data_source)
        counts[row["status"]] += 1
        _tally_excluded(row, excluded_tally)
        ws.append([row[key] for key in REPORT_HEADERS])
        if row["status"] == "fail":
            print(f"FAIL {row['doc_id'][:8]}  {row['title'][:60]}")
            print(f"     {row['excluded_details'][:200]}")

    wb.save(str(output_path))
    _print_summary(counts, excluded_tally)
    print(f"\nReport written to: {output_path}")


if __name__ == "__main__":
    main()
