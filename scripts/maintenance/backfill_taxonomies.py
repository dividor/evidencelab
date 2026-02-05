#!/usr/bin/env python3
"""
Backfill taxonomy tags for indexed documents.

This script re-runs the TaxonomyTagger on indexed documents that have summaries,
updating sys_taxonomies with all taxonomies defined in config.json. It does NOT
reprocess the entire document - only re-runs the tagging step.

Usage:
    # Dry run (default) - shows what would be done
    python scripts/maintenance/backfill_taxonomies.py --source uneg

    # Process all indexed documents
    python scripts/maintenance/backfill_taxonomies.py --source uneg --wet-run

    # Process with 4 parallel workers
    python scripts/maintenance/backfill_taxonomies.py --source uneg --wet-run --workers 4

    # Process only first 100 documents
    python scripts/maintenance/backfill_taxonomies.py --source uneg --wet-run --limit 100

    # Process specific document
    python scripts/maintenance/backfill_taxonomies.py --source uneg --wet-run --doc-id abc123

    # Process specific list of documents
    python scripts/maintenance/backfill_taxonomies.py --source uneg --wet-run \
        --records "id1,id2,id3"
"""

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add repo root to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from pipeline.db import get_db  # noqa: E402
from pipeline.db.config import load_datasources_config  # noqa: E402
from pipeline.processors.tagging.tagger_taxonomy import TaxonomyTagger  # noqa: E402

# Configure logging
log_dir = os.path.join(os.path.dirname(__file__), "../../logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "backfill_taxonomies.log")

# Force reconfiguration of logging
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

# Global tagger instance shared across workers
global_tagger = None


def process_doc_worker(doc_id, doc_data, data_source, wet_run):
    """
    Worker function to process a single document.
    Re-runs taxonomy tagging without full reprocessing.
    """
    thread_logger = logging.getLogger(f"worker_{doc_id[:8]}")
    db = get_db(data_source)

    try:
        title = doc_data.get("map_title") or "Unknown Title"
        summary = doc_data.get("sys_full_summary")

        if not summary:
            thread_logger.warning(f"Doc {doc_id} has no summary, skipping")
            return False

        thread_logger.info(f"Tagging doc {doc_id} ('{title[:60]}...')")

        # Use global tagger instance
        if not global_tagger:
            raise RuntimeError("Global tagger not initialized")

        # Build document dict with required fields for tagger
        document = {
            "doc_id": doc_id,
            "sys_full_summary": summary,
            "src_doc_raw_metadata": doc_data.get("src_doc_raw_metadata", {}),
        }

        # Run taxonomy tagging
        tagging_result = global_tagger.compute_document_tags(document)

        if not tagging_result:
            thread_logger.warning(f"No taxonomies generated for {doc_id}")
            return False

        # Extract sys_taxonomies dict (not the whole result with tag_* fields)
        sys_taxonomies = tagging_result.get("sys_taxonomies", {})

        if not sys_taxonomies:
            thread_logger.warning(f"No sys_taxonomies in result for {doc_id}")
            return False

        # Update sys_stages to mark taxonomy backfill
        sys_stages = doc_data.get("sys_stages", {})
        if "tag" not in sys_stages:
            sys_stages["tag"] = {}

        sys_stages["tag"]["timestamp"] = time.time()
        sys_stages["tag"]["method"] = "taxonomy_backfill"
        sys_stages["tag"]["taxonomies_count"] = len(sys_taxonomies)

        # Prepare sys_fields for update
        sys_fields = {"sys_stages": sys_stages, "sys_last_updated": time.time()}

        # Count total taxonomy values
        total_values = sum(
            len(values)
            for values in sys_taxonomies.values()
            if isinstance(values, list)
        )
        thread_logger.info(
            f"Generated {len(sys_taxonomies)} taxonomies "
            f"with {total_values} total values for {doc_id}"
        )

        if not wet_run:
            thread_logger.info(f"[DRY RUN] Would update doc {doc_id}")
        else:
            # Call merge_doc_sys_fields directly with sys_taxonomies parameter
            db.pg.merge_doc_sys_fields(
                doc_id=doc_id, sys_fields=sys_fields, sys_taxonomies=sys_taxonomies
            )
            thread_logger.info(f"Successfully updated taxonomies for {doc_id}")

        return True

    except Exception as e:
        thread_logger.error(f"Error processing {doc_id}: {e}", exc_info=True)
        return False


def backfill_taxonomies(
    data_source: str,
    dry_run: bool = True,
    limit: int = 0,
    target_doc_id: str = None,
    target_records: list = None,
    workers: int = 1,
):
    """
    Backfill taxonomy tags for indexed documents with summaries.
    """
    db = get_db(data_source)

    # Query for documents to process
    logger.info("Querying for indexed documents with summaries...")

    if target_doc_id:
        query = f"""
            SELECT doc_id, sys_full_summary, sys_stages, map_title, src_doc_raw_metadata
            FROM docs_{data_source}
            WHERE doc_id = %s
        """
        params = (target_doc_id,)
    elif target_records:
        placeholders = ",".join(["%s"] * len(target_records))
        query = f"""
            SELECT doc_id, sys_full_summary, sys_stages, map_title, src_doc_raw_metadata
            FROM docs_{data_source}
            WHERE doc_id IN ({placeholders})
        """
        params = tuple(target_records)
    else:
        query = f"""
            SELECT doc_id, sys_full_summary, sys_stages, map_title, src_doc_raw_metadata
            FROM docs_{data_source}
            WHERE sys_status = 'indexed'
              AND sys_full_summary IS NOT NULL
            ORDER BY sys_last_updated DESC
        """
        params = None

    all_docs = {}
    with db.pg._get_conn() as conn:
        with conn.cursor() as cur:
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)

            for row in cur.fetchall():
                doc_id, summary, stages, title, metadata = row
                all_docs[str(doc_id)] = {
                    "sys_full_summary": summary,
                    "sys_stages": stages or {},
                    "map_title": title,
                    "src_doc_raw_metadata": metadata or {},
                }

    if not all_docs:
        logger.warning("No documents found matching criteria")
        return

    logger.info(f"Found {len(all_docs)} documents to process")

    if dry_run:
        logger.info("Dry run enabled. No actual updates will be performed.")

    if limit > 0:
        logger.info(f"Limiting to first {limit} documents")
        doc_ids = list(all_docs.keys())[:limit]
        all_docs = {doc_id: all_docs[doc_id] for doc_id in doc_ids}

    # Initialize TaxonomyTagger
    logger.info("Initializing TaxonomyTagger...")
    all_ds_config = load_datasources_config().get("datasources", {})
    ds_config = {}
    for key, val in all_ds_config.items():
        if val.get("data_subdir") == data_source or key == data_source:
            ds_config = val
            break

    if not ds_config:
        logger.error(f"Could not find configuration for data source: {data_source}")
        return

    pipeline_config = ds_config.get("pipeline", {})
    tag_config = pipeline_config.get("tag", {})

    if not tag_config:
        logger.error(f"No tag configuration found for data source: {data_source}")
        return

    # Check if there are any taxonomies configured
    taxonomies = tag_config.get("taxonomies", {})
    if not taxonomies:
        logger.error("No taxonomies configured in tag configuration")
        return

    logger.info(f"Found {len(taxonomies)} taxonomies: {list(taxonomies.keys())}")

    global global_tagger
    global_tagger = TaxonomyTagger(config=tag_config)

    # Process with workers
    success_count = 0
    error_count = 0

    logger.info(f"Starting processing with {workers} workers...")

    affected_ids = list(all_docs.keys())

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                process_doc_worker, doc_id, all_docs[doc_id], data_source, not dry_run
            ): doc_id
            for doc_id in affected_ids
        }

        for i, future in enumerate(as_completed(future_map)):
            doc_id = future_map[future]
            try:
                if future.result():
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Exception for doc {doc_id}: {e}")
                error_count += 1

            if (i + 1) % 10 == 0:
                logger.info(f"Progress: {i + 1}/{len(affected_ids)} completed")

    logger.info(f"Finished. Success: {success_count}, Errors: {error_count}")
    logger.info(f"Full log available at: {log_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill taxonomy tags for indexed documents"
    )
    parser.add_argument("--source", default="uneg", help="Data source name")
    parser.add_argument("--wet-run", action="store_true", help="Execute updates")
    parser.add_argument(
        "--limit", type=int, default=0, help="Limit number of docs to process"
    )
    parser.add_argument("--doc-id", help="Target specific document ID")
    parser.add_argument(
        "--workers", type=int, default=1, help="Number of parallel workers"
    )
    parser.add_argument("--records", help="Comma-separated list of doc IDs")
    args = parser.parse_args()

    records_list = None
    if args.records:
        records_list = [r.strip() for r in args.records.split(",") if r.strip()]

    backfill_taxonomies(
        args.source,
        dry_run=not args.wet_run,
        limit=args.limit,
        target_doc_id=args.doc_id,
        target_records=records_list,
        workers=args.workers,
    )
