import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add repo root to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from fastembed import TextEmbedding  # noqa: E402

from pipeline.db import get_db  # noqa: E402
from pipeline.db.config import load_datasources_config  # noqa: E402
from pipeline.processors.summarization.summarizer import (  # noqa: E402
    SummarizeProcessor,
)

# Configure logging
log_dir = os.path.join(os.path.dirname(__file__), "../../logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "duplicate_summary_fix.log")

# Force reconfiguration of logging to ensure file handler is attached
# regardless of prior imports initializing the root logger.
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

# Global variable to hold the shared summarizer instance
global_summarizer = None


def process_doc_worker(doc_id, doc_data, data_source, wet_run):
    """
    Worker function to process a single document.
    """
    thread_logger = logging.getLogger(f"worker_{doc_id[:8]}")
    # Get a dedicated DB connection for this thread
    db = get_db(data_source)

    try:
        original_status = doc_data.get("sys_status")

        # Correction for previous double-nesting bug
        if "sys_data" in doc_data and isinstance(doc_data["sys_data"], dict):
            thread_logger.warning(
                f"Detected double-nested sys_data in {doc_id}, flattening..."
            )
            doc_data = doc_data["sys_data"]
            original_status = doc_data.get(
                "sys_status"
            )  # re-read status after flattening

        title = doc_data.get("title") or doc_data.get("map_title") or "Unknown Title"

        # Construct doc payload for processor
        doc_payload = {
            "doc_id": doc_id,
            "sys_parsed_folder": doc_data.get("sys_parsed_folder"),
            "map_title": title,
            "sys_id": doc_id,  # Pass ID just in case
        }

        thread_logger.info(
            f"Fixing doc {doc_id} ('{title}') via complete re-summarization..."
        )

        # Use the processor's standard logic to re-generate summary from SOURCE (markdown)
        # This avoids the "garbage-in-garbage-out" loop of summarizing the corrupted summary.
        # Use valid global instance
        if not global_summarizer:
            raise RuntimeError("Global summarizer not initialized")

        result = global_summarizer.process_document(doc_payload)

        if result.get("success"):
            updates = result.get("updates", {})

            # Add our specific metadata
            sys_stages = doc_data.get("sys_stages", {})
            # Merge the new summarize stage info
            if "sys_stages" in updates:
                # updates['sys_stages'] only contains the 'summarize' key usually
                sys_stages.update(updates["sys_stages"])
                # Mark specifically as duplicate fix
                # Also ensure method is set to 'llm_summary' or 'duplicate_fixer_rebuild'
                if "summarize" in sys_stages:
                    sys_stages["summarize"]["method"] = "duplicate_fixer_rebuild"

            updates["sys_stages"] = sys_stages
            updates["sys_last_updated"] = time.time()

            # Preserve 'indexed' status if it was already indexed
            # The processor typically returns sys_status="summarized"
            if original_status == "indexed":
                if "sys_status" in updates:
                    thread_logger.info(
                        f"Preserving existing status '{original_status}' "
                        f"(preventing regression to '{updates['sys_status']}')"
                    )
                    del updates["sys_status"]

            # CORRECT PAYLOAD: pass updates directly (flat), do NOT wrap in sys_data
            final_payload = updates
            # Ensure we don't accidentally send a sys_data key if it was in updates (unlikely)

            if not wet_run:
                thread_logger.info(f"[DRY RUN] Would update doc {doc_id}")
            else:
                db.update_document(doc_id, final_payload)
                thread_logger.info(f"Successfully rebuilt summary for {doc_id}")
            return True
        else:
            error = result.get("error", "Unknown error")
            thread_logger.error("Failed to generate summary for %s: %s", doc_id, error)
            return False

    except Exception as e:
        thread_logger.error("Error processing %s: %s", doc_id, e)
        return False


def fix_duplicate_summaries(
    data_source: str,
    dry_run: bool = True,
    limit: int = 0,
    target_doc_id: str = None,
    target_records: list = None,
    workers: int = 1,
):
    """
    Fixes documents where the summary appears to be a concatenation of multiple summaries.
    This re-processes the existing 'sys_full_summary' through the summarizer.
    """
    db = get_db(data_source)

    # 1. Identify affected documents
    logger.info("Querying for affected documents...")

    query = f"""
        SELECT doc_id, sys_data, map_title
        FROM docs_{data_source}
        WHERE sys_data ->> 'sys_full_summary' IS NOT NULL
    """

    all_docs = {}
    # Access protected member _get_conn from PostgresClient
    # pylint: disable=protected-access
    with db.pg._get_conn() as conn:  # type: ignore
        with conn.cursor() as cur:
            cur.execute(query)
            for doc_id, sys_data, map_title in cur.fetchall():
                data = sys_data or {}
                if map_title:
                    data["map_title"] = map_title
                all_docs[str(doc_id)] = data

    affected_ids = []

    # Regex to detect multiple summaries headers
    header_pattern = re.compile(
        r"(?:^|\n)(?:\*\*Summary:\*\*|#{1,6}\s*Summary|Summary\s*:)", re.IGNORECASE
    )

    for doc_id, sys_data in all_docs.items():
        summary = sys_data.get("sys_full_summary", "")
        matches = list(header_pattern.finditer(summary))
        if len(matches) > 1:
            affected_ids.append(doc_id)

    if target_doc_id:
        if target_doc_id in all_docs:
            logger.info(f"Targeting specific document: {target_doc_id}")
            affected_ids = [target_doc_id]
        else:
            logger.error(
                f"Target document {target_doc_id} not found in DB or has no summary."
            )
            return

    if target_records:
        valid_targets = []
        for rid in target_records:
            if rid in all_docs:
                valid_targets.append(rid)
            else:
                logger.warning(f"Record {rid} not found in DB or has no summary.")

        if valid_targets:
            logger.info(f"Targeting {len(valid_targets)} specific records.")
            affected_ids = valid_targets
        else:
            logger.error("No valid records found in target list.")
            return

    logger.info(f"Found {len(affected_ids)} documents to process.")

    if dry_run:
        logger.info("Dry run enabled. No actual updates will be performed.")

    if not affected_ids:
        return

    if limit > 0:
        logger.info(f"Limiting to first {limit} documents.")
        affected_ids = affected_ids[:limit]

    # 2. Initialize Summarizer
    # Correctly look up datasource config by data_subdir or name
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
    sum_config = pipeline_config.get("summarize", {})

    # Force enable if not
    sum_config["enabled"] = True
    # Limit inner workers to 1 to avoid OOM when running multiple docs in parallel
    sum_config["llm_workers"] = 1

    global global_summarizer
    global_summarizer = SummarizeProcessor(config=sum_config)

    logger.info("Initializing embedding model...")
    model_name = os.getenv("DENSE_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    embedding_model = TextEmbedding(model_name=model_name)

    global_summarizer.setup(embedding_model=embedding_model)

    # 3. Process with workers
    success_count = 0
    error_count = 0

    logger.info(f"Starting processing with {workers} workers...")

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
                logger.info(f"Progress: {i + 1}/{len(affected_ids)} completed.")

    logger.info(f"Finished. Success: {success_count}, Errors: {error_count}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
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

    fix_duplicate_summaries(
        args.source,
        dry_run=not args.wet_run,
        limit=args.limit,
        target_doc_id=args.doc_id,
        target_records=records_list,
        workers=args.workers,
    )
