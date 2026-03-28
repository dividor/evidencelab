"""MCP document retrieval tool — fetch full document metadata."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from mcp_server.schemas import MCPDocumentResponse

logger = logging.getLogger(__name__)


async def mcp_get_document(
    doc_id: str,
    data_source: Optional[str] = None,
) -> MCPDocumentResponse:
    """Retrieve metadata for a specific evaluation document.

    Returns the full document record including title, organization,
    publication year, abstract, AI-generated summary, and all
    available metadata fields.

    Args:
        doc_id: The unique document identifier.
        data_source: Data collection containing the document
            (e.g. "uneg", "worldbank").

    Returns:
        MCPDocumentResponse with document metadata.

    Raises:
        ValueError: If the document is not found.
    """
    from ui.backend.utils.app_state import get_pg_for_source

    pg = get_pg_for_source(data_source)
    docs = pg.fetch_docs([doc_id])
    doc = docs.get(str(doc_id))

    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    # Merge sys_data sub-fields into the top level for convenience
    sys_data = doc.get("sys_data") or {}
    if isinstance(sys_data, dict):
        for key, value in sys_data.items():
            if key not in doc:
                doc[key] = value

    # Build metadata dict from all available fields
    metadata: Dict[str, Any] = {}
    for key, value in doc.items():
        if key.startswith("map_") or key.startswith("sys_"):
            clean_key = key.replace("map_", "").replace("sys_", "")
            metadata[clean_key] = value

    return MCPDocumentResponse(
        doc_id=str(doc_id),
        title=doc.get("map_title", ""),
        organization=doc.get("map_organization"),
        year=doc.get("map_published_year"),
        abstract=sys_data.get("abstract") or doc.get("abstract"),
        summary=doc.get("sys_full_summary") or doc.get("sys_summary"),
        metadata=metadata,
    )
