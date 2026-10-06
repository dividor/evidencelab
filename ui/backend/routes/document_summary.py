"""Document summaries from the Documents screen — superuser-only routes.

Administrators can regenerate a document's summary with AI (choosing the
mode, sections and prompt), edit it, and save it. Generating never saves;
saving writes the summary, marks it as set in the app (so reprocessing keeps
it) and records an audit event.
"""

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from pipeline.processors.summarization.summary_text import (
    SUMMARY_MODES,
    SummaryTooLargeError,
)
from pipeline.processors.tagging.tagger_constants import SECTION_TYPES
from ui.backend.auth.audit import write_audit_event
from ui.backend.auth.models import User
from ui.backend.auth.users import current_superuser
from ui.backend.routes.config import get_config_model_combos
from ui.backend.services import document_summary as service
from ui.backend.services.llm_service import summarize_usage_metadata
from ui.backend.services.usage_recorder import schedule_llm_usage_recording
from ui.backend.utils.app_limits import get_rate_limits, limiter
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source

logger = logging.getLogger(__name__)

router = APIRouter()
_RL_SEARCH, _RL_DEFAULT, RATE_LIMIT_AI = get_rate_limits()

EVENT_SUMMARY_UPDATED = "document_summary_updated"
ACTIVITY_TYPE = "document_summary"
MAX_SUMMARY_CHARS = 50000


class SummaryModelConfig(BaseModel):
    """The summarization model of the model combo selected in the app."""

    model: str = Field(..., min_length=1, max_length=200)
    max_tokens: int = Field(2000, ge=100, le=65536)
    temperature: Optional[float] = Field(None, ge=0, le=2)


class GenerateSummaryRequest(BaseModel):
    data_source: str
    mode: Literal["map_reduce", "single_prompt"]
    section_types: List[str] = Field(..., max_length=len(SECTION_TYPES))
    prompt: str = Field(..., min_length=1, max_length=service.MAX_PROMPT_CHARS)
    summary_model: SummaryModelConfig

    @field_validator("section_types")
    @classmethod
    def _known_section_types(cls, value: List[str]) -> List[str]:
        unknown = [s for s in value if s not in SECTION_TYPES]
        if unknown:
            raise ValueError(f"Unknown section types: {unknown}")
        if not value:
            raise ValueError("Choose at least one section type")
        return value


class SaveSummaryRequest(BaseModel):
    data_source: str
    summary: str = Field(..., min_length=1, max_length=MAX_SUMMARY_CHARS)
    method: Literal["ui_map_reduce", "ui_single_prompt", "ui_edited"]


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _pg(data_source: str) -> Any:
    try:
        return get_pg_for_source(data_source)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data_source")


def _load_document(pg: Any, doc_id: str) -> Dict[str, Any]:
    doc = pg.fetch_docs([doc_id]).get(str(doc_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _check_model(data_source: str, model: str) -> None:
    """Only a summarization model of one of the data source's combos may be used."""
    combos = get_config_model_combos(data_source)
    allowed = {
        (combo.get("summarization_model") or {}).get("model")
        for combo in combos.values()
    }
    if model not in allowed:
        raise HTTPException(status_code=400, detail="Unknown summarization model")


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/settings")
@limiter.limit(_RL_DEFAULT)
async def get_summary_settings(
    request: Request,
    data_source: Optional[str] = Query(None, description="Data source key"),
    admin: User = Depends(current_superuser),
) -> Dict[str, Any]:
    """Defaults for summaries generated in the app (superuser only).

    Always returns the default prompt, the modes and the section types; with a
    data source, also its configured mode, sections and single-prompt window.
    """
    settings: Dict[str, Any] = {
        "prompt": service.default_summary_instructions(),
        "modes": list(SUMMARY_MODES),
        "all_section_types": list(SECTION_TYPES),
    }
    if data_source:
        _pg(data_source)
        settings.update(service.summary_defaults(data_source))
    return settings


@router.get("/{doc_id}/sections")
@limiter.limit(_RL_DEFAULT)
async def get_summary_sections(
    request: Request,
    doc_id: str,
    data_source: str = Query(..., description="Data source key"),
    max_tokens: int = Query(2000, ge=100, le=65536),
    admin: User = Depends(current_superuser),
) -> Dict[str, Any]:
    """The document's text per section type, and how much a single prompt can take."""
    pg = _pg(data_source)
    await run_in_threadpool(_load_document, pg, doc_id)
    chunks = await run_in_threadpool(pg.fetch_chunks_for_doc, doc_id)
    return {
        "has_section_types": service.has_section_types(chunks),
        "sections": service.section_breakdown(chunks),
        "single_prompt_limit_chars": service.single_prompt_limit(
            data_source, max_tokens
        ),
    }


@router.post("/{doc_id}/generate")
@limiter.limit(RATE_LIMIT_AI)
async def generate_document_summary(
    request: Request,
    doc_id: str,
    body: GenerateSummaryRequest,
    admin: User = Depends(current_superuser),
) -> StreamingResponse:
    """Generate a summary with AI and stream progress (superuser only).

    Frames: ``meta`` (whether the document has section types), ``progress``
    (``single``, ``map`` with done/total, or ``reduce``), then ``done`` with
    the summary or ``error`` with a message. Nothing is saved.
    """
    pg = _pg(body.data_source)
    doc = await run_in_threadpool(_load_document, pg, doc_id)
    _check_model(body.data_source, body.summary_model.model)
    chunks = await run_in_threadpool(pg.fetch_chunks_for_doc, doc_id)
    title = doc.get("map_title") or str(doc_id)
    return StreamingResponse(
        _generation_stream(body, doc_id, chunks, title, admin),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _generation_stream(
    body: GenerateSummaryRequest,
    doc_id: str,
    chunks: List[Dict[str, Any]],
    title: str,
    admin: User,
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress(event: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "progress", **event})

    async def run() -> None:
        try:
            result = await run_in_threadpool(
                service.generate_summary,
                body.data_source,
                doc_id,
                chunks,
                mode=body.mode,
                section_types=body.section_types,
                prompt=body.prompt,
                model=body.summary_model.model,
                max_tokens=body.summary_model.max_tokens,
                temperature=body.summary_model.temperature,
                progress=progress,
            )
            usage = summarize_usage_metadata(
                result.pop("usage"), body.summary_model.model
            )
            schedule_llm_usage_recording(
                usage=usage,
                activity_type=ACTIVITY_TYPE,
                query=f"Document summary: {title}",
                user_id=getattr(admin, "id", None),
            )
            await queue.put({"type": "done", **result})
        except (SummaryTooLargeError, service.DocumentSummaryError) as exc:
            await queue.put({"type": "error", "error": str(exc)})
        except Exception:
            logger.exception("Document summary generation failed for %s", doc_id)
            await queue.put(
                {"type": "error", "error": "The summary could not be generated."}
            )

    task = asyncio.create_task(run())
    yield _sse({"type": "meta", "has_section_types": service.has_section_types(chunks)})
    while True:
        frame = await queue.get()
        yield _sse(frame)
        if frame["type"] in ("done", "error"):
            break
    await task


@router.put("/{doc_id}")
@limiter.limit(_RL_DEFAULT)
async def save_document_summary(
    request: Request,
    doc_id: str,
    body: SaveSummaryRequest,
    admin: User = Depends(current_superuser),
) -> Dict[str, Any]:
    """Save a document's summary (superuser only), with an audit event."""
    pg = _pg(body.data_source)
    doc = await run_in_threadpool(_load_document, pg, doc_id)
    db = get_db_for_source(body.data_source)
    updates = service.summary_updates(body.summary, body.method, admin.email)
    try:
        await run_in_threadpool(db.update_document, doc_id, updates)
    except Exception:
        logger.exception("Failed to save the summary of document %s", doc_id)
        raise HTTPException(status_code=500, detail="Could not save the summary")

    await write_audit_event(
        EVENT_SUMMARY_UPDATED,
        user_id=admin.id,
        user_email=admin.email,
        ip_address=_client_ip(request),
        details={
            "doc_id": str(doc_id),
            "data_source": body.data_source,
            "title": doc.get("map_title"),
            "method": body.method,
            "previous_method": (doc.get("sys_data") or {}).get(
                "sys_summarization_method"
            ),
            "chars": len(body.summary),
        },
    )
    return {
        "doc_id": str(doc_id),
        "full_summary": body.summary,
        "summarization_method": body.method,
        "summary_user_set": True,
        "summary_updated_by": updates[service.UPDATED_BY_FIELD],
        "summary_updated_at": updates[service.UPDATED_AT_FIELD],
    }
