"""Processing helpers for pipeline orchestration."""

import logging
import multiprocessing
import time
from typing import Any, Dict

from pipeline.orchestrator.core_docs import (
    apply_filters,
    collect_docs_by_stage,
    dedupe_docs_by_id,
    get_partition_slice,
    sort_recent_first,
)
from pipeline.orchestrator.worker import (
    _generate_processing_log,
    init_worker,
    process_document_wrapper,
)

logger = logging.getLogger(__name__)


def run_processing(orchestrator, limit: int = None) -> Dict[str, Any]:
    """
    Run per-document processing using ProcessPoolExecutor.
    """
    steps = _build_processing_steps(orchestrator)

    step_desc = " → ".join(steps)
    logger.info("STEP: Per-Document Processing (%s)", step_desc)
    if orchestrator.partition:
        logger.info("Partition: %s", orchestrator.partition)
    logger.info("=" * 60)

    docs_to_process = _collect_documents(orchestrator)

    if not docs_to_process:
        logger.info("No documents found for processing.")
        return {"processed": 0, "success": 0, "failed": 0}

    docs_to_process = dedupe_docs_by_id(docs_to_process)
    docs_to_process = apply_filters(
        docs_to_process, orchestrator.agency, orchestrator.report
    )
    if not docs_to_process:
        return {"processed": 0, "success": 0, "failed": 0}

    if orchestrator.recent_first:
        docs_to_process = sort_recent_first(docs_to_process)

    if orchestrator.partition:
        docs_to_process = get_partition_slice(
            docs_to_process, orchestrator.partition_num, orchestrator.partition_total
        )

    if limit:
        docs_to_process = docs_to_process[:limit]

    logger.info("Found %s documents to process", len(docs_to_process))

    stats = {"processed": 0, "success": 0, "failed": 0}

    if orchestrator.workers > 1:
        _process_docs_parallel(orchestrator, docs_to_process, stats)
    else:
        _process_docs_sequential(orchestrator, docs_to_process, stats)

    logger.info(
        "\n✅ Processing complete: %s/%s succeeded",
        stats["success"],
        stats["processed"],
    )
    return stats


def mark_as_stopped(orchestrator, doc_id: str, reason: str) -> None:
    """Mark a document as stopped in the DB due to worker crash/timeout."""
    try:
        if not hasattr(orchestrator.db, "update_document"):
            logger.warning(
                "Skipping stop update for doc %s (db has no update_document)", doc_id
            )
            return
        orchestrator.db.update_document(
            doc_id,
            {
                "sys_status": "stopped",
                "sys_error_message": reason,
                "sys_last_updated": time.time(),
            },
            wait=True,
        )
        logger.warning("⚠️ Marked doc %s as STOPPED: %s", doc_id, reason)
        try:
            doc = orchestrator.db.get_document(doc_id)
            if doc and doc.get("sys_parsed_folder"):
                _generate_processing_log(doc_id, doc.get("sys_parsed_folder"))
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Failed to generate logs for stopped doc %s: %s", doc_id, exc)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("Failed to mark doc %s as stopped: %s", doc_id, exc)


def _build_processing_steps(orchestrator) -> list[str]:
    steps = []
    if not orchestrator.skip_parse:
        steps.append("Parse")
    if not orchestrator.skip_summarize:
        steps.append("Summarize")
    if not orchestrator.skip_tag:
        steps.append("Tag")
    if not orchestrator.skip_index:
        steps.append("Index")
    return steps


def _collect_documents(orchestrator) -> list:
    if orchestrator.doc_id:
        logger.info("Targeting specific document ID: %s", orchestrator.doc_id)
        doc = orchestrator.db.get_document(orchestrator.doc_id)
        if doc:
            doc["id"] = orchestrator.doc_id
            return [doc]

        logger.error("Document %s not found in DB", orchestrator.doc_id)
        return []

    return collect_docs_by_stage(
        orchestrator.db,
        orchestrator.skip_index,
        orchestrator.skip_tag,
        orchestrator.skip_summarize,
        orchestrator.skip_parse,
        orchestrator.report,
        orchestrator.recent_first,
    )


def _process_docs_parallel(orchestrator, docs_to_process: list, stats: Dict[str, int]):
    logger.info(
        "Using %s parallel workers (multiprocessing.Pool)", orchestrator.workers
    )
    ctx = multiprocessing.get_context("spawn")

    with ctx.Pool(
        processes=orchestrator.workers,
        initializer=init_worker,
        initargs=(
            orchestrator.data_source,
            orchestrator.skip_parse,
            orchestrator.skip_summarize,
            orchestrator.skip_index,
            orchestrator.skip_tag,
            orchestrator.save_chunks,
            orchestrator.pipeline_config,
        ),
        maxtasksperchild=5,
    ) as pool:
        pending_results = {}
        for doc in docs_to_process:
            res = pool.apply_async(process_document_wrapper, (doc,))
            pending_results[doc.get("id")] = (res, doc)

        logger.info("Submitted %s tasks to pool...", len(pending_results))

        for doc_id, (res, doc) in pending_results.items():
            try:
                result = res.get(timeout=600)

                stats["processed"] += 1

                if "error" in result:
                    stats["failed"] += 1
                    mark_as_stopped(
                        orchestrator,
                        doc_id,
                        f"Worker Error: {result.get('error', 'Unknown error')}",
                    )
                elif not result.get("stages"):
                    pass
                else:
                    if all(s.get("success", False) for s in result["stages"].values()):
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1

            except (multiprocessing.context.TimeoutError, TimeoutError):
                logger.error(
                    "❌ Worker timed out or hung processing doc %s (possible OOM)",
                    doc_id,
                )
                mark_as_stopped(orchestrator, doc_id, "Worker Timeout/OOM")
                stats["failed"] += 1

            except (OSError, RuntimeError, ValueError) as exc:
                logger.error("❌ Worker crashed processing doc %s: %s", doc_id, exc)
                mark_as_stopped(orchestrator, doc_id, f"Worker Crash: {exc}")
                stats["failed"] += 1


def _process_docs_sequential(
    orchestrator, docs_to_process: list, stats: Dict[str, int]
):
    logger.info("Running sequentially (1 worker)")
    init_worker(
        orchestrator.data_source,
        orchestrator.skip_parse,
        orchestrator.skip_summarize,
        orchestrator.skip_index,
        orchestrator.skip_tag,
        orchestrator.save_chunks,
        orchestrator.pipeline_config,
    )

    for doc in docs_to_process:
        try:
            result = process_document_wrapper(doc)
            stats["processed"] += 1
            if "error" in result:
                stats["failed"] += 1
                mark_as_stopped(
                    orchestrator,
                    doc.get("id"),
                    f"Worker Error: {result.get('error', 'Unknown error')}",
                )
            elif result["stages"]:
                if all(s.get("success", False) for s in result["stages"].values()):
                    stats["success"] += 1
                else:
                    stats["failed"] += 1
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Error processing %s: %s", doc.get("title"), exc)
            stats["processed"] += 1
            stats["failed"] += 1
            mark_as_stopped(orchestrator, doc.get("id"), f"Worker Crash: {exc}")
