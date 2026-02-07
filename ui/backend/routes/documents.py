import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from qdrant_client.http import models as qmodels

import pipeline.utilities.tasks as pipeline_tasks
from pipeline.utilities.text_cleaning import clean_text
from ui.backend.schemas import DocumentMetadataUpdate, TocUpdate
from ui.backend.services import llm_service as llm_service_module
from ui.backend.utils.app_limits import get_rate_limits
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source, logger
from ui.backend.utils.document_utils import normalize_document_payload
from ui.backend.utils.documents_sys_merge import merge_sys_data_for_doc

RATE_LIMIT_SEARCH, RATE_LIMIT_DEFAULT, RATE_LIMIT_AI = get_rate_limits()
celery_app = pipeline_tasks.app
router = APIRouter()


def _get_llm_service():
    """Resolve the LLM service module from runtime or fallback imports."""
    return (
        sys.modules.get("llm_service")
        or sys.modules.get("ui.backend.services.llm_service")
        or llm_service_module
    )


def _resolve_parsed_folder(doc: Dict[str, Any]) -> Optional[str]:
    parsed_folder = doc.get("sys_parsed_folder")
    if not parsed_folder:
        sys_data = doc.get("sys_data")
        if isinstance(sys_data, dict):
            parsed_folder = sys_data.get("sys_parsed_folder")
    if not parsed_folder:
        return None
    data_mount_path = os.getenv("DATA_MOUNT_PATH", "./data")
    if parsed_folder.startswith("data/"):
        parsed_folder = os.path.join(data_mount_path, parsed_folder[5:])
    return os.path.normpath(parsed_folder)


def _read_processing_log(log_file_path: str) -> Optional[str]:
    if not os.path.exists(log_file_path):
        return None
    with open(log_file_path, "r", encoding="utf-8") as handle:
        return handle.read()


def _resolve_log_dir(script_dir: str) -> str:
    log_dir = os.getenv("LOG_DIR")
    if log_dir:
        if not os.path.isabs(log_dir):
            log_dir = os.path.join(script_dir, log_dir)
    else:
        log_dir = os.path.join(script_dir, "logs")
    if not os.path.exists(log_dir) and os.path.exists("/app/logs"):
        log_dir = "/app/logs"
    return log_dir


def _run_analyze_logs(
    analyze_logs_script: str,
    log_dir: str,
    doc_id: str,
    parsed_folder: str,
) -> None:
    subprocess.run(
        [
            sys.executable,
            analyze_logs_script,
            log_dir,
            "--file-id",
            doc_id,
            "--parsed-folder",
            parsed_folder,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _processing_log_path(parsed_folder: str) -> str:
    return os.path.join(parsed_folder, "processing.log")


def _read_processing_log_safe(log_file_path: str) -> Optional[str]:
    return _read_processing_log(log_file_path)


def _generate_processing_log(
    analyze_logs_script: str,
    log_dir: str,
    doc_id: str,
    parsed_folder: str,
) -> None:
    _run_analyze_logs(analyze_logs_script, log_dir, doc_id, parsed_folder)
    if not os.path.exists(_processing_log_path(parsed_folder)) and doc_id.isdigit():
        logger.info("Trying integer version of doc_id: %s", int(doc_id))
        _run_analyze_logs(analyze_logs_script, log_dir, str(int(doc_id)), parsed_folder)


def _resolve_task_output(task_id: str) -> Optional[str]:
    res = celery_app.AsyncResult(task_id)
    if isinstance(res.info, dict) and "log" in res.info:
        return res.info["log"]
    if res.state == "FAILURE":
        return f"Error: {str(res.result)}"
    return None


def _enrich_active_tasks(active: Dict[str, List[Dict[str, Any]]]) -> None:
    for tasks in active.values():
        for task in tasks:
            try:
                task_id = task.get("id")
                if not task_id:
                    continue
                output = _resolve_task_output(task_id)
                if output:
                    task["output"] = output
            except Exception:
                pass


def _build_document_filters(
    organization: Optional[str],
    document_type: Optional[str],
    published_year: Optional[str],
    language: Optional[str],
    file_format: Optional[str],
    status: Optional[str],
    title: Optional[str],
    search: Optional[str],
    toc_approved: Optional[bool],
    sdg: Optional[str],
    cross_cutting_theme: Optional[str],
) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if organization:
        filters["organization"] = organization
    if document_type:
        filters["document_type"] = document_type
    if published_year:
        filters["published_year"] = published_year
    if toc_approved is not None:
        filters["toc_approved"] = toc_approved
    if sdg:
        # Split comma-separated values for multiselect
        filters["sdg"] = [s.strip() for s in sdg.split(",") if s.strip()]
    if cross_cutting_theme:
        # Split comma-separated values for multiselect
        filters["cross_cutting_theme"] = [
            c.strip() for c in cross_cutting_theme.split(",") if c.strip()
        ]
    if language:
        filters["language"] = language
    if file_format:
        filters["file_format"] = file_format
    if status:
        filters["status"] = status
    if title:
        filters["title"] = title
    if search:
        filters["search"] = search
    return filters


async def _translate_documents(
    documents: List[Dict[str, Any]],
    target_language: str,
) -> None:
    if not target_language or target_language.lower() == "en":
        return
    llm_service = _get_llm_service()

    async def translate_doc(doc):
        doc_lang = doc.get("language", "en") or "en"
        if doc_lang.lower().startswith(target_language.lower()):
            return

        doc["_original_title"] = doc.get("title")
        doc["_original_summary"] = doc.get("full_summary")
        doc["_original_language"] = doc_lang
        doc["_translated"] = True

        if doc.get("title"):
            doc["title"] = await llm_service.translate_text(
                doc["title"], target_language
            )

        if doc.get("full_summary"):
            summary = doc["full_summary"]
            if len(summary) > 2000:
                parts = summary[:2000].rsplit(".", 1)
                to_translate = parts[0] + "."
                doc["full_summary"] = await llm_service.translate_text(
                    to_translate, target_language
                )
            else:
                doc["full_summary"] = await llm_service.translate_text(
                    summary, target_language
                )

    tasks = [translate_doc(doc) for doc in documents]
    await asyncio.gather(*tasks)


@router.get("/documents")
async def get_documents(
    organization: str = Query(None, description="Filter by organization"),
    document_type: str = Query(None, description="Filter by document type"),
    published_year: str = Query(None, description="Filter by published year"),
    language: str = Query(None, description="Filter by language"),
    file_format: str = Query(
        None, description="Filter by file format (e.g., pdf, docx)"
    ),
    status: str = Query(None, description="Filter by status"),
    title: str = Query(None, description="Filter by title (partial match)"),
    search: str = Query(None, description="Global search across title and summary"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
    target_language: str = Query(
        None, description="Target language for translation (e.g., 'fr', 'es')"
    ),
    toc_approved: Optional[bool] = Query(
        None, description="Filter by TOC approval status"
    ),
    sdg: str = Query(
        None, description="Filter by SDG (comma-separated for multiple, e.g. sdg1,sdg5)"
    ),
    cross_cutting_theme: str = Query(
        None,
        description="Filter by cross-cutting theme (comma-separated for multiple)",
    ),
    sort_by: str = Query("year", description="Field to sort by"),
    order: str = Query("desc", description="Sort order (asc/desc)"),
):
    """
    Get documents with optional filtering and pagination.
    Returns list of documents with metadata and pagination info.
    Filters support partial matching (case-insensitive contains) for text fields
    and exact matching for keyword fields (via Qdrant indices).
    Taxonomy filters support multiselect via comma-separated values.
    """
    try:
        # Use Postgres instead of Qdrant for listing documents
        pg = get_pg_for_source(data_source)
        filters = _build_document_filters(
            organization,
            document_type,
            published_year,
            language,
            file_format,
            status,
            title,
            search,
            toc_approved,
            sdg,
            cross_cutting_theme,
        )

        # Run blocking Postgres call in a separate thread to avoid blocking the event loop
        result = await run_in_threadpool(
            pg.get_paginated_documents,
            page=page,
            page_size=page_size,
            filters=filters,
            sort_by=sort_by,
            sort_order=order,
        )

        # Normalize result format to match frontend expectations
        result["documents"] = [
            normalize_document_payload(doc) for doc in result["documents"]
        ]

        # Merge sys fields is likely not needed if Postgres already returns them,
        # but we check if normalize_document_payload handles it.
        # merge_sys_data_fields is designed for Qdrant results that need sys_data unpacked.
        # Postgres get_paginated_documents returns unpacked structure, so we might skip merge.
        # However, to be safe and consistent with previous logic if normalize
        # depends on specific keys:
        # The Postgres implementation returns a dict structure very similar to
        # what normalize expects.

        await _translate_documents(result["documents"], target_language)
        return result

    except Exception as e:
        logger.error(f"Error getting documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/document/{doc_id}")
async def get_document(
    doc_id: str,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """Get full document metadata"""
    try:
        doc = None
        try:
            pg = get_pg_for_source(data_source)
            doc = pg.fetch_docs([doc_id]).get(str(doc_id))
            if doc:
                merge_sys_data_for_doc(doc)
        except Exception:
            doc = None
        if not doc:
            db = get_db_for_source(data_source)
            doc = db.get_document(doc_id) if db else None
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        doc = normalize_document_payload(doc)

        # Clean metadata fields
        for key in ["title", "abstract", "organization", "author"]:
            if key in doc and isinstance(doc[key], str):
                doc[key] = clean_text(doc[key])

        return doc
    except Exception as e:
        logger.error(f"Document fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/document/{doc_id}/logs")
async def get_document_logs(
    doc_id: str,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """Get processing logs for a document"""
    try:
        db = get_db_for_source(data_source)
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        parsed_folder = _resolve_parsed_folder(doc)
        if not parsed_folder:
            return {"logs": "", "error": "No parsed folder found for this document"}

        log_file_path = _processing_log_path(parsed_folder)
        logs_content = _read_processing_log_safe(log_file_path)
        if logs_content is not None:
            return {"logs": logs_content, "source": "file"}

        script_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        analyze_logs_script = os.path.join(
            script_dir, "scripts", "utils", "analyze_logs.py"
        )
        log_dir = _resolve_log_dir(script_dir)

        _generate_processing_log(analyze_logs_script, log_dir, doc_id, parsed_folder)
        logs_content = _read_processing_log_safe(log_file_path)
        if logs_content is not None:
            return {"logs": logs_content, "source": "generated"}

        logger.warning(
            "No logs found for doc_id=%s (tried both string and int formats)", doc_id
        )
        return {"logs": "", "error": "No logs found for this document."}
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        return {"logs": "", "error": f"Error getting logs: {str(e)}"}


@router.put("/document/{doc_id}/toc")
async def update_document_toc(
    doc_id: str,
    toc_update: TocUpdate,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """Update the toc_classified field for a document"""
    try:
        db = get_db_for_source(data_source)
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # Update the toc_classified field and set user_edited flag
        doc["sys_toc_classified"] = toc_update.toc_classified
        doc["sys_user_edited_section_types"] = True
        db.update_document(doc_id, doc)

        logger.info(f"Updated TOC for document {doc_id} (user edited)")
        return {"success": True, "message": "TOC updated successfully"}
    except Exception as e:
        logger.error(f"TOC update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/documents/{doc_id}")
async def update_document_metadata(
    doc_id: str,
    update: DocumentMetadataUpdate,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """
    Update arbitrary document metadata fields.
    Currently supported: toc_approved
    """
    try:
        db = get_db_for_source(data_source)
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # Apply updates
        updates_made = False
        if update.toc_approved is not None:
            doc["sys_toc_approved"] = update.toc_approved
            updates_made = True

        if updates_made:
            if hasattr(db, "update_document"):
                db.update_document(doc_id, {"sys_toc_approved": update.toc_approved})
            else:
                pg = get_pg_for_source(data_source)
                pg.merge_doc_sys_fields(
                    doc_id=str(doc_id),
                    sys_fields={"sys_toc_approved": update.toc_approved},
                )
            doc = normalize_document_payload(doc)
            logger.info(
                f"Updated metadata for document {doc_id}: {update.dict(exclude_unset=True)}"
            )
            return {
                "success": True,
                "message": "Document updated successfully",
                "doc": doc,
            }
        else:
            return {"success": True, "message": "No changes requested"}

    except Exception as e:
        logger.error(f"Document update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(
    doc_id: str,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
    target_language: str = Query(
        None, description="Target language for translation (e.g., 'fr', 'es')"
    ),
):
    """Get all chunks for a specific document"""
    try:
        db = get_db_for_source(data_source)
        pg = get_pg_for_source(data_source)

        # Query chunks from Qdrant for this document
        results, _ = db.client.scroll(
            collection_name=db.chunks_collection,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id", match=qmodels.MatchValue(value=doc_id)
                    )
                ]
            ),
            limit=10000,  # Get all chunks for the document
            with_payload=True,
        )

        chunk_cache = pg.fetch_chunks([str(point.id) for point in results])

        formatted_chunks = []
        for point in results:
            payload = point.payload
            chunk_payload = chunk_cache.get(str(point.id), {})
            formatted_chunks.append(
                {
                    "chunk_id": str(point.id),
                    "doc_id": payload.get("doc_id"),
                    "text": clean_text(payload.get("sys_text", "")),
                    "page_num": chunk_payload.get("sys_page_num"),
                    "headings": chunk_payload.get("sys_headings", []),
                    "bbox": chunk_payload.get("sys_bbox", []),
                    "section_type": payload.get("tag_section_type"),
                    "score": 1.0,
                }
            )

        # Translate chunks if target_language is set
        if target_language and target_language.lower() != "en":
            # Check document language first to avoid unnecessary translation
            doc = pg.fetch_docs([doc_id]).get(str(doc_id))
            doc = normalize_document_payload(doc) if doc else None
            doc_lang = (doc.get("language") if doc else "en") or "en"

            if not doc_lang.lower().startswith(target_language.lower()):
                llm_service = _get_llm_service()

                async def translate_chunk(chunk):
                    """Translate a chunk's text into the target language."""
                    if chunk.get("text"):
                        chunk["_original_text"] = chunk["text"]
                        chunk["_translated"] = True
                        chunk["text"] = await llm_service.translate_text(
                            chunk["text"], target_language
                        )

                # Translate in parallel
                tasks = [translate_chunk(chunk) for chunk in formatted_chunks]
                await asyncio.gather(*tasks)

        return {"chunks": formatted_chunks, "total": len(formatted_chunks)}

    except Exception as e:
        logger.error(f"Chunks fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{doc_id}/reprocess-toc")
async def reprocess_document_toc(
    doc_id: str,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """Reprocess TOC classification for a document and update chunk tags.

    NOTE: This does NOT change the document status - it only updates
    toc_classified and chunk section_type tags.
    """
    try:
        resolved_source = data_source if isinstance(data_source, str) else None
        task_module = sys.modules.get("pipeline.utilities.tasks", pipeline_tasks)
        # Enqueue the background task
        task = task_module.reprocess_document_toc.delay(
            doc_id=doc_id, data_source=resolved_source
        )
        logger.info(
            f"Triggered background TOC reprocess for doc {doc_id}, task_id={task.id}"
        )

        return {
            "success": True,
            "message": "Background processing started",
            "task_id": str(task.id),
        }

    except Exception as e:
        logger.error(f"TOC reprocess error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue/status")
async def get_queue_status():
    """
    Get the status of the Celery queue (active, reserved, scheduled).
    """
    try:
        # Use the global celery_app instance directly
        # The import inside the function was causing an ImportError/circular dependency
        # because we are potentially in the main module or it's not importable this way.
        # Assuming celery_app is defined globally in this file (it usually is for FastAPI + Celery).

        # If celery_app is not global, we should check where it is initialized.
        # But generally in single-file or main.py setups, it's global.

        i = celery_app.control.inspect()

        # Timeout slightly in case workers are busy
        active = i.active() or {}
        reserved = i.reserved() or {}
        scheduled = i.scheduled() or {}

        _enrich_active_tasks(active)

        return {"active": active, "reserved": reserved, "scheduled": scheduled}
    except Exception as e:
        logger.error(f"Queue status error: {e}")
        return {"error": str(e), "active": {}, "reserved": {}, "scheduled": {}}


@router.post("/documents/{doc_id}/reprocess")
async def reprocess_document(
    doc_id: str,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """
    Reprocess a document through the full pipeline (parse, summarize, tag, index).

    Resets status, deletes chunks, and enqueues task for pipeline worker.
    """
    source = data_source or "uneg"
    db = get_db_for_source(source)
    doc = db.get_document(doc_id)
    doc = normalize_document_payload(doc) if doc else doc
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    filepath = doc.get("filepath")
    if not filepath:
        raise HTTPException(status_code=400, detail="Document has no filepath")

    # Prepare document for reprocessing
    db.delete_document_chunks(doc_id)
    db.update_document(doc_id, {"sys_status": "queued", "sys_error_message": None})

    # Enqueue task for Celery worker (runs in pipeline container)
    task_module = sys.modules.get("pipeline.utilities.tasks", pipeline_tasks)
    task = task_module.reprocess_document.delay(doc_id, filepath, source)

    return {
        "success": True,
        "message": "Reprocessing queued",
        "doc_id": doc_id,
        "task_id": task.id,
    }


@router.get("/pdf/{doc_id}")
async def serve_pdf(
    doc_id: str,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """Serve PDF file for viewing"""
    try:
        doc = None
        try:
            pg = get_pg_for_source(data_source)
            doc = pg.fetch_docs([doc_id]).get(str(doc_id))
            if doc:
                sys_data = doc.get("sys_data")
                if isinstance(sys_data, dict) and "sys_filepath" in sys_data:
                    doc.setdefault("sys_filepath", sys_data.get("sys_filepath"))
        except Exception:
            doc = None
        if not doc:
            db = get_db_for_source(data_source)
            doc = db.get_document(doc_id) if db else None
        doc = normalize_document_payload(doc) if doc else doc
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        filepath = doc.get("filepath") or doc.get("sys_filepath")
        if not filepath:
            raise HTTPException(
                status_code=404, detail="PDF filepath not found in metadata"
            )

        # Convert relative path to absolute path
        pdf_path = Path(filepath)
        if not pdf_path.is_absolute():
            # Assume paths are relative to /app (Docker container working directory)
            pdf_path = Path("/app") / filepath

        if not pdf_path.exists():
            raise HTTPException(
                status_code=404, detail=f"PDF file not found at {pdf_path}"
            )

        # Read PDF and return with explicit inline disposition
        with open(pdf_path, "rb") as f:
            pdf_content = f.read()

        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PDF serve error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Allowed file extensions for static file serving
ALLOWED_FILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@router.get("/file/{file_path:path}")
async def serve_file(file_path: str):
    """
    Serve static files (images, etc.) from the data directory.
    Used for table images and other extracted content.
    """
    try:
        # Security: URL decode the path to catch encoded traversal attempts
        # Double decode to catch double-encoding attacks (%252e%252e -> %2e%2e -> ..)
        decoded_path = unquote(unquote(file_path))

        # Reject null bytes which can be used for path truncation attacks
        if "\x00" in decoded_path or "\x00" in file_path:
            logger.warning(f"Null byte injection attempt blocked: {file_path}")
            raise HTTPException(status_code=400, detail="Invalid file path")

        # Check for path traversal sequences in decoded path
        if ".." in decoded_path:
            logger.warning(f"Path traversal attempt blocked: {file_path}")
            raise HTTPException(status_code=403, detail="Access denied")

        # Convert absolute path to relative if needed
        # Images may be stored with DATA_MOUNT_PATH prefix, need to convert to data/ prefix
        data_mount_path = os.environ.get("DATA_MOUNT_PATH") or "/mnt/files/evaluation-db"
        # Strip leading slash from both for comparison (since file_path comes from URL)
        data_mount_normalized = data_mount_path.lstrip("/")
        if data_mount_normalized and decoded_path.startswith(data_mount_normalized):
            # Replace mount path with 'data'
            decoded_path = "data" + decoded_path[len(data_mount_normalized) :]

        # Construct full path - files are relative to APP_ROOT (defaults to /app)
        app_root = Path(os.environ.get("APP_ROOT", "/app")).resolve()

        # Resolve the path to get canonical form and prevent traversal
        try:
            full_path = (app_root / decoded_path).resolve()
        except (ValueError, OSError) as e:
            logger.warning(f"Invalid path resolution: {file_path} - {e}")
            raise HTTPException(status_code=400, detail="Invalid file path")

        # Verify the resolved path is under the allowed base directory
        allowed_base = (app_root / "data").resolve()
        try:
            full_path.relative_to(allowed_base)
        except ValueError:
            # Path is not under the allowed base directory
            logger.warning(
                f"Path traversal attempt blocked (outside data dir): {file_path}"
            )
            raise HTTPException(status_code=403, detail="Access denied")

        # Verify file extension is allowed
        if full_path.suffix.lower() not in ALLOWED_FILE_EXTENSIONS:
            logger.warning(f"Disallowed file type requested: {file_path}")
            raise HTTPException(status_code=403, detail="File type not allowed")

        if not full_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

        # Determine media type based on extension
        suffix = full_path.suffix.lower()
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }
        media_type = media_types.get(suffix, "application/octet-stream")

        return FileResponse(str(full_path), media_type=media_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File serve error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
