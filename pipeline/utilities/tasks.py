"""Celery tasks for background pipeline processing."""

import logging
import os
from collections import deque

from celery import Celery

import pipeline.db as pipeline_db
import pipeline.orchestrator as pipeline_orchestrator
import pipeline.processors.tagging.tagger as tagger_module

logger = logging.getLogger(__name__)

# Create Celery app
app = Celery(
    "pipeline",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
)

# Configure Celery
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,  # 30 minutes max per task
    worker_prefetch_multiplier=1,  # Don't prefetch, process one at a time
)


@app.task(bind=True, name="pipeline.reprocess_document")
def reprocess_document(self, doc_id: str, filepath: str, data_source: str = "uneg"):
    """
    Reprocess a document through the full pipeline.

    This task runs in the pipeline container with all ML models loaded.
    """
    logger.info("Starting reprocess task for doc %s: %s", doc_id, filepath)

    try:
        # Get database connection
        db = pipeline_db.get_db(data_source)

        # Clear is_duplicate flag so the document isn't excluded from queries
        # Keep status as "queued" during model loading (can take minutes)
        db.update_document(doc_id, {"is_duplicate": False})

        # Create orchestrator - this loads all ML models (slow)
        orchestrator = pipeline_orchestrator.PipelineOrchestrator(
            data_source=data_source,
            skip_download=True,
            skip_scan=True,
            report=filepath,
            num_records=1,
            doc_id=doc_id,
        )

        # Now set status to "downloaded" so orchestrator.run() picks it up
        # Use wait=True to ensure Orchestrator sees the updated status immediately
        db.update_document(doc_id, {"sys_status": "downloaded"}, wait=True)

        # Setup log capture to update task state
        orchestrator_logger = logging.getLogger("pipeline.orchestrator")

        class TaskLogHandler(logging.Handler):
            """Log handler that streams recent logs into task state."""

            def __init__(self, task):
                super().__init__()
                self.task = task
                self.log_buffer = deque(maxlen=50)

            def emit(self, record):
                try:
                    msg = self.format(record)
                    self.log_buffer.append(msg)
                    # Send last 10 lines as a single string
                    full_log = "\n".join(self.log_buffer)
                    self.task.update_state(state="PROGRESS", meta={"log": full_log})
                except Exception:  # pylint: disable=broad-exception-caught
                    self.handleError(record)

        # Attach handler
        log_handler = TaskLogHandler(self)
        orchestrator_logger.addHandler(log_handler)
        # Ensure levels allow info
        orchestrator_logger.setLevel(logging.INFO)

        try:
            # Run the pipeline
            orchestrator.run()
        finally:
            # Clean up handler
            orchestrator_logger.removeHandler(log_handler)

        logger.info("Reprocess completed for doc %s", doc_id)
        return {"success": True, "doc_id": doc_id}

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Reprocess failed for doc %s: %s", doc_id, e)
        # Update status to error
        try:
            db = pipeline_db.get_db(data_source)
            db.update_document(
                doc_id, {"sys_status": "error", "sys_error_message": str(e)[:500]}
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        raise


@app.task(bind=True, name="pipeline.reprocess_document_toc")
def reprocess_document_toc(self, doc_id: str, data_source: str = "uneg"):
    """
    Reprocess TOC classification for a document and update chunk tags.
    """
    _ = self
    logger.info("Starting TOC reprocess task for doc %s", doc_id)

    try:
        db = pipeline_db.get_db(data_source)
        doc = db.get_document(doc_id)
        if not doc:
            logger.error("Document %s not found", doc_id)
            return {"success": False, "message": "Document not found"}

        doc["id"] = doc_id

        # Initialize the full TaggerProcessor (includes embedding model and all taggers)
        # This is the heavy part that was timing out in the API
        tagger = tagger_module.TaggerProcessor(data_source=data_source or "uneg")
        tagger.setup()

        # Find the section type tagger
        section_tagger = None
        # pylint: disable=protected-access
        for t in tagger._taggers:
            if isinstance(t, tagger_module.SectionTypeTagger):
                section_tagger = t
                # Clear cache for this document
                if doc_id in t._document_cache:
                    del t._document_cache[doc_id]
                break
        # pylint: enable=protected-access

        if not section_tagger:
            return {
                "success": False,
                "message": "SectionTypeTagger not found",
            }

        # Classify TOC directly (does NOT change status)
        classifications = section_tagger.classify_document_toc(doc)

        if not classifications:
            return {
                "success": False,
                "message": "No TOC found or classification failed",
            }

        # Reload document to get updated toc_classified
        doc = db.get_document(doc_id)
        doc["id"] = doc_id
        toc_classified = doc.get("sys_toc_classified", "")

        # Now update chunk section_type tags (also does NOT change status)
        tagger.tag_chunks_only(doc)

        logger.info("TOC Reprocess completed for doc %s", doc_id)
        return {
            "success": True,
            "message": f"Reprocessed TOC with {len(classifications)} classifications",
            "sys_toc_classified": toc_classified,
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("TOC Reprocess failed for doc %s: %s", doc_id, e)
        raise
