"""Hidden (moderated) documents: the one place that knows how the flag is stored.

An administrator can hide a document that breaches the content policy. A
hidden document stays in the library so it can be restored, but it must not
reach any user-facing path: chunk search (and everything built on it: the
assistant, MCP, A2A, facet counts narrowed by a query), document search,
title search, facet values, the document listing, and every by-id fetch.

Storage:

- PostgreSQL: ``sys_data->>'sys_hidden'`` (``true``) plus ``sys_hidden_reason``,
  ``sys_hidden_at`` and ``sys_hidden_by`` for the audit trail, written through
  ``PostgresClient.merge_doc_sys_fields``.
- Qdrant: payload key ``sys_hidden`` (``true``) on the document point and on
  every chunk point of the document, so a single ``must_not`` condition
  excludes them from any query.

Every query path uses :func:`exclude_hidden` or :data:`HIDDEN_SQL_CLAUSE`;
every by-id path uses :func:`is_hidden`. Nothing else should mention the
field name.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, Optional

from qdrant_client.http import models

logger = logging.getLogger(__name__)

HIDDEN_FIELD = "sys_hidden"
HIDDEN_REASON_FIELD = "sys_hidden_reason"
HIDDEN_AT_FIELD = "sys_hidden_at"
HIDDEN_BY_FIELD = "sys_hidden_by"

# Appended to the WHERE clause of PostgreSQL document listings and facet
# counts. Documents with no flag (the vast majority) have a NULL expression,
# and ``IS NOT TRUE`` keeps them.
HIDDEN_SQL_CLAUSE = f"(sys_data ->> '{HIDDEN_FIELD}')::boolean IS NOT TRUE"

# Maximum length of the free-text reason an administrator records.
MAX_HIDDEN_REASON_CHARS = 500


def hidden_condition() -> models.FieldCondition:
    """The Qdrant condition that matches hidden points."""
    return models.FieldCondition(key=HIDDEN_FIELD, match=models.MatchValue(value=True))


def _as_list(conditions: Any) -> List[models.Condition]:
    if conditions is None:
        return []
    if isinstance(conditions, list):
        return list(conditions)
    return [conditions]


def exclude_hidden(query_filter: Optional[models.Filter]) -> models.Filter:
    """Return ``query_filter`` with hidden points excluded.

    A ``None`` filter becomes a filter with only the exclusion; an existing
    filter keeps its ``must`` and ``should`` clauses and gains the exclusion
    in ``must_not``. The input is not mutated.
    """
    if query_filter is None:
        return models.Filter(must_not=[hidden_condition()])
    must_not = _as_list(query_filter.must_not)
    if not any(_is_hidden_condition(c) for c in must_not):
        must_not.append(hidden_condition())
    return models.Filter(
        must=query_filter.must,
        must_not=must_not,
        should=query_filter.should,
        min_should=getattr(query_filter, "min_should", None),
    )


def _is_hidden_condition(condition: Any) -> bool:
    return getattr(condition, "key", None) == HIDDEN_FIELD


def is_hidden(doc: Optional[Mapping[str, Any]]) -> bool:
    """True when a document record (from PostgreSQL or Qdrant) is hidden.

    Accepts the raw ``fetch_docs`` shape (flag inside ``sys_data``), the
    normalised API shape (``hidden``), and a Qdrant payload (``sys_hidden``).
    """
    if not doc:
        return False
    if doc.get(HIDDEN_FIELD) is True or doc.get("hidden") is True:
        return True
    sys_data = doc.get("sys_data")
    return isinstance(sys_data, Mapping) and sys_data.get(HIDDEN_FIELD) is True


def _point_id(doc_id: str) -> Any:
    """Qdrant stores numeric document ids as integers."""
    try:
        return int(doc_id)
    except ValueError:
        return doc_id


def set_document_hidden(
    db: Any,
    doc_id: str,
    hidden: bool,
    *,
    reason: Optional[str] = None,
    actor: Optional[str] = None,
) -> None:
    """Hide a document from every user-facing path, or restore it.

    ``db`` is a ``pipeline.db.database.Database`` (typed loosely to avoid an
    import cycle). Writes the flag (and who/why/when) to the document's
    PostgreSQL ``sys_data`` and sets the ``sys_hidden`` payload on the
    document point and on all of its chunk points, so the single
    ``must_not`` condition from :func:`exclude_hidden` excludes them
    everywhere. Restoring clears the flag but keeps the reason fields as
    history.
    """
    doc_key = str(doc_id)
    sys_fields: Dict[str, Any] = {HIDDEN_FIELD: bool(hidden)}
    if hidden:
        sys_fields[HIDDEN_REASON_FIELD] = reason or None
        sys_fields[HIDDEN_AT_FIELD] = time.time()
        sys_fields[HIDDEN_BY_FIELD] = actor or None
    db.pg.merge_doc_sys_fields(doc_id=doc_key, sys_fields=sys_fields)

    payload = {HIDDEN_FIELD: bool(hidden)}
    db.client.set_payload(
        collection_name=db.documents_collection,
        payload=payload,
        points=[_point_id(doc_key)],
        wait=True,
    )
    db.client.set_payload(
        collection_name=db.chunks_collection,
        payload=payload,
        points=models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_id", match=models.MatchValue(value=doc_key)
                )
            ]
        ),
        wait=True,
    )
    logger.info(
        "Document %s %s%s",
        doc_key,
        "hidden" if hidden else "restored",
        f" by {actor}" if actor else "",
    )
