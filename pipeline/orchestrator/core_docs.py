"""Document selection helpers for pipeline orchestration."""

import logging
from pathlib import Path
from typing import Any, Dict, List

from pipeline.processors.scanning.scanner import _make_relative_path

logger = logging.getLogger(__name__)


def get_documents_recent_first(db, status: str, limit: int | None = None) -> list:
    """
    Fetch documents for a status year-by-year (descending).
    Uses Qdrant facets to find which years exist, then fetches efficiently.
    """
    logger.info("Getting documents for status='%s' (Recent First)...", status)

    years = db.get_years_for_status(status)
    if not years:
        logger.info("  No years found in facets, falling back to basic fetch")
        return db.get_documents_by_status(status)

    logger.info("  Found years: %s", years)

    all_docs: List[Dict[str, Any]] = []
    for year in years:
        if limit and len(all_docs) >= limit:
            break

        docs_for_year = db.get_documents_by_status(status, year=year)
        if docs_for_year:
            logger.info("  Fetching %s: found %s docs", year, len(docs_for_year))
            docs_for_year.sort(key=lambda x: str(x.get("id")))
            all_docs.extend(docs_for_year)

    return all_docs


def get_docs_by_status(db, status: str, recent_first: bool) -> list:
    """Fetch documents for a status, optionally ordered by most recent year."""
    if recent_first:
        return get_documents_recent_first(db, status)
    return db.get_documents_by_status(status)


def collect_docs_by_stage(
    db,
    skip_index: bool,
    skip_tag: bool,
    skip_summarize: bool,
    skip_parse: bool,
    report: str | None,
    recent_first: bool,
) -> list:
    """Collect documents to process based on enabled pipeline stages."""
    docs_to_process: List[Dict[str, Any]] = []

    stage_configs = [
        ("tagged", not skip_index, "index"),
        ("summarized", (not skip_tag) or (not skip_index), "process"),
        (
            "parsed",
            (not skip_summarize) or (not skip_index),
            "index" if skip_summarize else "summarize",
        ),
    ]

    for status, enabled, action in stage_configs:
        if not enabled:
            continue
        docs = get_docs_by_status(db, status, recent_first)
        _extend_docs(docs_to_process, docs, status, action)

    if not skip_parse:
        docs = _collect_parse_docs(db, report, recent_first)
        docs_to_process.extend(docs)

    return docs_to_process


def _extend_docs(
    docs_to_process: List[Dict[str, Any]],
    docs: list,
    status: str,
    action: str,
) -> None:
    if not docs:
        return
    logger.info("Found %s %s documents to %s", len(docs), status, action)
    docs_to_process.extend(docs)


def _collect_parse_docs(
    db, report: str | None, recent_first: bool
) -> List[Dict[str, Any]]:
    if report:
        return _collect_all_docs(db)
    downloaded = get_docs_by_status(db, "downloaded", recent_first)
    if downloaded:
        logger.info("Found %s downloaded documents to parse", len(downloaded))
    return downloaded or []


def _collect_all_docs(db) -> List[Dict[str, Any]]:
    all_docs_list: List[Dict[str, Any]] = []
    for doc_id, doc in db.get_all_documents_with_ids():
        doc["id"] = doc_id
        all_docs_list.append(doc)
    return all_docs_list


def dedupe_docs_by_id(docs: list) -> list:
    """Remove duplicate documents by id, keeping the last seen entry."""
    unique_docs: Dict[Any, Dict[str, Any]] = {}
    for doc in docs:
        if doc.get("id"):
            unique_docs[doc["id"]] = doc
    return list(unique_docs.values())


def apply_filters(docs: list, agency: str | None, report: str | None) -> list:
    """Filter documents by agency or report substring if requested."""
    if agency:
        docs = [doc for doc in docs if doc.get("map_organization") == agency]

    if report:
        report_path = Path(report)
        if report_path.exists():
            report = _make_relative_path(str(report_path.resolve()))
        docs = [doc for doc in docs if report in (doc.get("sys_filepath") or "")]

    return docs


def sort_recent_first(docs: list) -> list:
    """Sort documents by year descending, handling missing/invalid years safely."""

    def safe_year(doc):
        try:
            return int(doc.get("map_published_year") or 0)
        except (ValueError, TypeError):
            return 0

    docs = sorted(docs, key=safe_year, reverse=True)
    years = [doc.get("published_year") for doc in docs[:5]]
    logger.info("Sorted by year (recent first): %s...", years)
    return docs


def get_partition_slice(
    docs: list, partition_num: int | None, partition_total: int | None
) -> list:
    """Return the partition slice for the current worker."""
    if not partition_num or not partition_total:
        return docs

    total_docs = len(docs)
    chunk_size = total_docs // partition_total
    remainder = total_docs % partition_total

    start = 0
    for i in range(1, partition_num):
        start += chunk_size + (1 if i <= remainder else 0)

    end = start + chunk_size + (1 if partition_num <= remainder else 0)

    logger.info(
        "Partition %s/%s: documents %s-%s of %s",
        partition_num,
        partition_total,
        start + 1,
        end,
        total_docs,
    )
    return docs[start:end]
