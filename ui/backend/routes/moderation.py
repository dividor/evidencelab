"""Content moderation — superuser-only routes.

Hides a document that breaches the content policy from every user-facing
path (search, listings, the research assistant, MCP and A2A) in one action,
and restores it. The flag is stored and the
exclusion logic lives in :mod:`pipeline.db.moderation`. Every action is
written to the audit log.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from pipeline.db.moderation import MAX_HIDDEN_REASON_CHARS, is_hidden
from pipeline.db.moderation import set_document_hidden as apply_hidden
from ui.backend.auth.audit import write_audit_event
from ui.backend.auth.models import User
from ui.backend.auth.users import current_superuser
from ui.backend.utils.app_limits import get_rate_limits, limiter
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source
from ui.backend.utils.document_utils import normalize_document_payload

logger = logging.getLogger(__name__)

router = APIRouter()
_RL_SEARCH, _RL_DEFAULT, _RL_AI = get_rate_limits()

EVENT_DOCUMENT_HIDDEN = "document_hidden"
EVENT_DOCUMENT_RESTORED = "document_restored"


class HideDocumentRequest(BaseModel):
    """Hide (``hidden=true``) or restore (``hidden=false``) a document."""

    hidden: bool
    reason: Optional[str] = Field(None, max_length=MAX_HIDDEN_REASON_CHARS)


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _load_document(pg: Any, doc_id: str) -> Dict[str, Any]:
    doc = pg.fetch_docs([doc_id]).get(str(doc_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/documents/{doc_id}/hidden")
@limiter.limit(_RL_DEFAULT)
async def set_document_hidden(
    request: Request,
    doc_id: str,
    body: HideDocumentRequest,
    data_source: Optional[str] = Query(None, description="Data source key"),
    admin: User = Depends(current_superuser),
) -> Dict[str, Any]:
    """Hide a document from the whole platform, or restore it (superuser only).

    Hiding removes the document from search, document listings, facets, the
    research assistant and the MCP/A2A endpoints while keeping it in the
    library so it can be restored. The action, the reason and the acting
    administrator are recorded in the audit log.
    """
    pg = get_pg_for_source(data_source)
    doc = await run_in_threadpool(_load_document, pg, doc_id)
    db = get_db_for_source(data_source)
    reason = (body.reason or "").strip() or None

    try:
        await run_in_threadpool(
            apply_hidden,
            db,
            doc_id,
            body.hidden,
            reason=reason,
            actor=admin.email,
        )
    except Exception:
        logger.exception("Failed to set hidden=%s on document %s", body.hidden, doc_id)
        raise HTTPException(status_code=500, detail="Could not update the document")

    await write_audit_event(
        EVENT_DOCUMENT_HIDDEN if body.hidden else EVENT_DOCUMENT_RESTORED,
        user_id=admin.id,
        user_email=admin.email,
        ip_address=_client_ip(request),
        details={
            "doc_id": str(doc_id),
            "data_source": data_source,
            "title": doc.get("map_title"),
            "reason": reason,
        },
    )
    logger.info(
        "Admin %s %s document %s (%s)",
        admin.email,
        "hid" if body.hidden else "restored",
        doc_id,
        reason or "no reason given",
    )
    return {
        "doc_id": str(doc_id),
        "hidden": body.hidden,
        "reason": reason,
        "was_hidden": is_hidden(doc),
    }


@router.get("/documents/hidden")
@limiter.limit(_RL_DEFAULT)
async def list_hidden_documents(
    request: Request,
    data_source: Optional[str] = Query(None, description="Data source key"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: User = Depends(current_superuser),
) -> Dict[str, Any]:
    """List the documents currently hidden in a data source (superuser only)."""
    pg = get_pg_for_source(data_source)
    result = await run_in_threadpool(
        pg.get_paginated_documents,
        page=page,
        page_size=page_size,
        filters={"include_hidden": True, "hidden": True},
        sort_by="last_updated",
        sort_order="desc",
    )
    result["documents"] = [
        normalize_document_payload(doc) for doc in result.get("documents", [])
    ]
    return result
