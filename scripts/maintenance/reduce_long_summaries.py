import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

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
log_file = os.path.join(log_dir, "reduce_long_summaries.log")

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

global_summarizer = None


def process_doc_worker(doc_id, doc_data, data_source, wet_run):
    """
    Worker function to process a single document by re-reducing its existing summary.
    """
    thread_logger = logging.getLogger(f"worker_{doc_id[:8]}")
    db = get_db(data_source)

    try:
        existing_summary = doc_data.get("sys_full_summary", "")
        if not existing_summary:
            thread_logger.warning(f"Doc {doc_id} has no summary to reduce.")
            return False

        mapped_title = doc_data.get("map_title", "Unknown Title")
        thread_logger.info(
            f"Reducing summary for {doc_id} ('{mapped_title}') "
            f"(Length: {len(existing_summary)} chars)..."
        )

        # Access internal method _llm_summary to skip file reading
        # and directly summarize the text content
        if not global_summarizer:
            raise RuntimeError("Global summarizer not initialized")

        # _llm_summary returns (final_summary, intermediate_summaries)
        # It handles the recursion logic internally now.
        final_summary, _ = global_summarizer._llm_summary(existing_summary)

        if not final_summary:
            thread_logger.error(
                f"Failed to reduce summary for {doc_id} (returned None)"
            )
            return False

        if final_summary == "USE_CENTROID":
            # Fallback if map-reduce fails
            thread_logger.warning(
                f"Map-reduce failed for {doc_id}, falling back to centroid strategy..."
            )
            # We need to construct a fake 'doc' dict for _summarize_with_centroid
            # But wait, centroid needs the original content to split sentences.
            # If we only have the summary, centroid might not be great if the summary
            # is just a few chunks.
            # But the user asked to use the existing summary.
            # So we treat the existing long summary as the "content".
            # So we manually call _centroid_summary
            final_summary = global_summarizer._centroid_summary(
                existing_summary, mapped_title
            )
            if not final_summary:
                thread_logger.error("Centroid fallback failed.")
                return False

        # Calculate reduction stats
        original_len = len(existing_summary)
        new_len = len(final_summary)
        reduction_ratio = (1 - (new_len / original_len)) * 100

        thread_logger.info(
            f"Reduced {doc_id}: {original_len} -> {new_len} chars "
            f"({reduction_ratio:.1f}% reduction)"
        )

        if len(final_summary) > original_len:
            thread_logger.warning(
                f"New summary is larger than original! Skipping update for {doc_id}."
            )
            return False

        # Prepare updates
        sys_stages = doc_data.get("sys_stages", {})
        if "summarize" not in sys_stages:
            sys_stages["summarize"] = {}

        sys_stages["summarize"].update(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "method": "recursive_reduction_fix",
                "success": True,
            }
        )

        updates = {
            "sys_full_summary": final_summary,
            "sys_stages": sys_stages,
            "sys_last_updated": time.time(),
        }

        # Preserve status if indexed
        original_status = doc_data.get("sys_status")
        # Correction for previous double-nesting bug just in case
        if "sys_data" in doc_data and isinstance(doc_data["sys_data"], dict):
            original_status = doc_data["sys_data"].get("sys_status")

        if original_status != "indexed":
            # If not indexed, maybe set to summarized?
            # But if it was "summarizing", we set to "summarized"
            if original_status in ["summarizing", "pending", "failed"]:
                updates["sys_status"] = "summarized"

        if not wet_run:
            thread_logger.info(f"[DRY RUN] Would update doc {doc_id}")
        else:
            db.update_document(doc_id, updates)
            thread_logger.info(f"Successfully updated {doc_id}")

        return True

    except Exception as e:
        thread_logger.error(f"Error processing {doc_id}: {e}")


def fix_long_summaries(
    data_source: str,
    dry_run: bool = True,
    limit: int = 0,
    target_doc_id: str = None,
    target_records: list = None,
    workers: int = 1,
):
    db = get_db(data_source)
    logger.info("Querying for affected documents...")

    # Same query logic
    query = f"""
        SELECT doc_id, sys_data, map_title
        FROM docs_{data_source}
        WHERE sys_data ->> 'sys_full_summary' IS NOT NULL
    """

    all_docs = {}
    with db.pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            for doc_id, sys_data, map_title in cur.fetchall():
                data = sys_data or {}
                if map_title:
                    data["map_title"] = map_title
                all_docs[str(doc_id)] = data

    affected_ids = []
    # Same regex logic
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
            logger.error(f"Target {target_doc_id} not found/no summary")
            return

    if target_records:
        # Filter affected_ids to only those in target_records
        # (We still only process if they actually have duplicate summaries,
        #  unless we want to force process? usually 'affected_ids' comes from regex match.
        #  If the user provides explicit records they usually want those processed
        #  regardless of regex? Actually script logic first finds ALL docs, then filters.
        #  If I want to force process specific records even if regex doesn't match,
        #  I should change logic. But usually users use this on known bad docs.
        #  Let's stick to intersection for safety: only process if it WAS found as affected
        #  OR if explicitly requested?
        #  Wait, previous logic for target_doc_id: checks if in `all_docs` then sets
        #  `affected_ids = [target_doc_id]`.
        #  `all_docs` contains *all* docs with a summary.
        #  The regex loop (lines 186-190) populates `affected_ids`.
        #  The `target_doc_id` block (lines 192-198) OVERRIDES `affected_ids`.
        #  So `target_doc_id` forces processing even if regex didn't match.
        #  (as long as it has a summary).
        #  I should do the same for `target_records`.

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
        logger.info("Dry run enabled. No actual updates.")

    if not affected_ids:
        return

    if limit > 0:
        logger.info(f"Limiting to first {limit} documents.")
        affected_ids = affected_ids[:limit]

    # Initialize Summarizer
    all_ds_config = load_datasources_config().get("datasources", {})
    ds_config = {}
    for key, val in all_ds_config.items():
        if val.get("data_subdir") == data_source or key == data_source:
            ds_config = val
            break

    if not ds_config:
        logger.error("No config found")
        return

    pipeline_config = ds_config.get("pipeline", {})
    sum_config = pipeline_config.get("summarize", {})
    sum_config["enabled"] = True
    sum_config["llm_workers"] = 1  # Force inner sequential

    global global_summarizer
    global_summarizer = SummarizeProcessor(config=sum_config)

    logger.info("Initializing embedding model...")
    model_name = os.getenv("DENSE_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    embedding_model = TextEmbedding(model_name=model_name)
    global_summarizer.setup(embedding_model=embedding_model)

    start_time = time.time()
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
                logger.error(f"Exception for {doc_id}: {e}")
                error_count += 1

            if (i + 1) % 10 == 0:
                logger.info(f"Progress: {i+1}/{len(affected_ids)}")

    elapsed = time.time() - start_time
    logger.info(
        f"Finished in {elapsed:.1f}s. Success: {success_count}, Errors: {error_count}"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="uneg")
    parser.add_argument("--wet-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--doc-id")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--records", help="Comma-separated list of doc IDs")
    args = parser.parse_args()

    records_list = None
    if args.records:
        records_list = [r.strip() for r in args.records.split(",") if r.strip()]

    fix_long_summaries(
        args.source,
        dry_run=not args.wet_run,
        limit=args.limit,
        target_doc_id=args.doc_id,
        target_records=records_list,
        workers=args.workers,
    )
