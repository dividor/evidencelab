"""
Search tools for the research assistant agent.

Wraps the existing search infrastructure (search_chunks from search.py)
for use by the LangGraph research agent.
"""

import logging
from typing import Any, Dict, List, Optional

from ui.backend.services.search import search_chunks

logger = logging.getLogger(__name__)


def search_documents(
    query: str,
    data_source: Optional[str] = None,
    limit: int = 20,
    filters: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    """
    Search indexed documents in Qdrant.

    Wraps the existing search_chunks function for use by the research
    assistant agent.

    Args:
        query: Search query string
        data_source: Optional data source to search within
        limit: Maximum number of results
        filters: Optional Qdrant filters

    Returns:
        List of search result dicts with doc_id, title, text, score, etc.
    """
    try:
        results = search_chunks(
            query=query,
            limit=limit,
            data_source=data_source,
            filters=filters,
            rerank=True,
        )

        formatted = []
        for r in results:
            payload = r.payload if hasattr(r, "payload") else r
            formatted.append(
                {
                    "chunk_id": getattr(r, "id", payload.get("chunk_id", "")),
                    "doc_id": payload.get("doc_id", ""),
                    "title": payload.get("title", "Untitled"),
                    "text": payload.get("text", ""),
                    "score": getattr(r, "score", payload.get("score", 0.0)),
                    "page": payload.get("page_num", None),
                    "headings": payload.get("headings", []),
                }
            )

        logger.info(
            "Assistant search: query=%r, data_source=%s, results=%d",
            query[:80],
            data_source,
            len(formatted),
        )
        return formatted

    except Exception as exc:
        logger.error("Assistant search failed: %s", exc, exc_info=True)
        return []


def get_document_detail(
    doc_id: str,
    data_source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieve detailed document metadata and chunks.

    Args:
        doc_id: Document identifier
        data_source: Optional data source

    Returns:
        Document metadata dict
    """
    try:
        results = search_chunks(
            query="",
            limit=50,
            data_source=data_source,
            filters={"doc_id": doc_id},
        )

        chunks: List[Dict[str, Any]] = []
        doc_meta: Dict[str, Any] = {}
        for r in results:
            payload = r.payload if hasattr(r, "payload") else r
            if not doc_meta:
                doc_meta = {
                    "doc_id": payload.get("doc_id", doc_id),
                    "title": payload.get("title", ""),
                    "organization": payload.get("organization", ""),
                }
            chunks.append(
                {
                    "text": payload.get("text", ""),
                    "page": payload.get("page_num", None),
                    "headings": payload.get("headings", []),
                }
            )

        doc_meta["chunks"] = chunks
        return doc_meta

    except Exception as exc:
        logger.error("Document detail retrieval failed: %s", exc, exc_info=True)
        return {"doc_id": doc_id, "error": str(exc)}
