"""MCP / A2A audit log read routes (admin only)."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.users import current_superuser

logger = logging.getLogger(__name__)
router = APIRouter()


class McpAuditEntry(BaseModel):
    id: int
    created_at: str
    protocol: str
    tool_name: str
    auth_type: str
    user_id: Optional[str] = None
    client_ip: Optional[str] = None
    duration_ms: Optional[float] = None
    status: str
    error_message: Optional[str] = None
    output_summary: Optional[str] = None


class McpAuditResponse(BaseModel):
    items: List[McpAuditEntry]
    total: int
    page: int
    page_size: int


@router.get("/", response_model=McpAuditResponse)
async def list_mcp_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    protocol: Optional[str] = Query(None, description="Filter by 'mcp' or 'a2a'"),
    status: Optional[str] = Query(None, description="Filter by 'ok' or 'error'"),
    _user=Depends(current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Return a paginated, newest-first list of MCP/A2A audit log entries."""
    where_clauses = []
    bind_params: dict = {}

    if protocol:
        where_clauses.append("protocol = :protocol")
        bind_params["protocol"] = protocol
    if status:
        where_clauses.append("status = :status")
        bind_params["status"] = status

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM mcp_audit_log {where_sql}"),
        bind_params,
    )
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    bind_params["limit"] = page_size
    bind_params["offset"] = offset

    rows = await db.execute(
        text(
            f"""
            SELECT id, created_at, protocol, tool_name, auth_type,
                   user_id, client_ip, duration_ms, status,
                   error_message, output_summary
            FROM mcp_audit_log
            {where_sql}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        bind_params,
    )

    items = [
        McpAuditEntry(
            id=row.id,
            created_at=(
                row.created_at.isoformat()
                if hasattr(row.created_at, "isoformat")
                else str(row.created_at)
            ),
            protocol=row.protocol,
            tool_name=row.tool_name,
            auth_type=row.auth_type,
            user_id=row.user_id or None,
            client_ip=row.client_ip,
            duration_ms=row.duration_ms,
            status=row.status,
            error_message=row.error_message,
            output_summary=row.output_summary,
        )
        for row in rows.mappings()
    ]

    return McpAuditResponse(items=items, total=total, page=page, page_size=page_size)
