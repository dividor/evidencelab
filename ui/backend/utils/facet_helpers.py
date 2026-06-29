"""Helpers for building facet results from Qdrant and PostgreSQL."""

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from ui.backend.schemas import FacetValue, RangeInfo
from ui.backend.utils.language_codes import LANGUAGE_NAMES

logger = logging.getLogger(__name__)

# Maximum unique values allowed for a dynamic (src_*/tag_*) filter field.
# Fields exceeding this limit must be purely numerical (rendered as range
# inputs) or removed from filter_fields in config.json.
FILTER_FIELD_MAX_UNIQUE_VALS = 1000


def _all_values_numerical(raw_counts: Dict[Any, int]) -> bool:
    """Return True if every non-empty key can be parsed as a number."""
    has_values = False
    for key in raw_counts:
        if key is None or key == "":
            continue
        has_values = True
        try:
            float(str(key))
        except (ValueError, TypeError):
            return False
    return has_values


def _build_range_info(raw_counts: Dict[Any, int]) -> RangeInfo:
    """Compute min/max from numerical facet keys."""
    nums = [float(str(k)) for k in raw_counts if k is not None and k != ""]
    return RangeInfo(min=min(nums), max=max(nums))


def build_year_facets(raw_counts: Dict[Any, int]) -> List[FacetValue]:
    year_items = []
    for raw_value, count in raw_counts.items():
        if raw_value is None or raw_value == "":
            continue
        year_items.append((str(raw_value), count))
    year_items.sort(key=lambda item: item[0], reverse=True)
    return [FacetValue(value=value, count=count) for value, count in year_items]


def _looks_like_concatenated(value: str) -> bool:
    """Return True if a value appears to be multiple items joined without a separator.

    Detects patterns like ``"BangladeshCambodiaIndia"`` where a lowercase
    letter is immediately followed by an uppercase letter (indicating two
    words were concatenated without any delimiter).  Requires at least two
    such transitions to avoid false positives on legitimate values like
    ``"McDonald's"``.
    """
    return len(re.findall(r"[a-z][A-Z]", value)) >= 2


def _split_multivalue(raw_value: str) -> List[str]:
    """Split a multi-value string on '; ' or ' | ' separators.

    Comma is NOT used as a separator because many values legitimately
    contain commas (e.g. ``"Egypt, Arab Rep."``, ``"Gambia, The"``).
    """
    if "; " in raw_value:
        return [p.strip() for p in raw_value.split("; ") if p.strip()]
    if " | " in raw_value:
        return [p.strip() for p in raw_value.split(" | ") if p.strip()]
    return []


def _accumulate_raw_value(counter: Counter, raw_value: Any, count: int) -> None:
    """Add a single raw facet value (possibly multi-valued) to *counter*."""
    if raw_value is None or raw_value == "":
        return
    if isinstance(raw_value, str):
        parts = _split_multivalue(raw_value)
        if parts:
            for item in parts:
                if not _looks_like_concatenated(item):
                    counter[item] += count
            return
        if _looks_like_concatenated(raw_value):
            return
    counter[str(raw_value)] += count


def build_generic_facets(raw_counts: Dict[Any, int]) -> List[FacetValue]:
    counter: Counter[str] = Counter()
    for raw_value, count in raw_counts.items():
        _accumulate_raw_value(counter, raw_value, count)
    return [
        FacetValue(value=value, count=count) for value, count in counter.most_common()
    ]


def expand_multivalue_filter(db, storage_field: str, selected: List[str]) -> List[str]:
    """Expand individual filter values to include raw multi-value entries.

    When ``map_country`` stores ``"Nepal; India"`` and the user selects
    ``"Nepal"``, this returns ``["Nepal", "Nepal; India"]`` so the Qdrant
    MatchAny filter matches both single- and multi-country documents.
    """
    raw_counts = db.facet_documents(
        key=storage_field, filter_conditions=None, limit=5000, exact=False
    )
    selected_set = set(selected)
    expanded = set(selected)
    for raw_value in raw_counts:
        raw_str = str(raw_value)
        if "; " in raw_str or " | " in raw_str:
            sep = "; " if "; " in raw_str else " | "
            parts = {p.strip() for p in raw_str.split(sep)}
            if parts & selected_set:
                expanded.add(raw_str)
    return list(expanded)


def build_facets_from_pg(pg, storage_field: str) -> Dict[str, int]:
    """Get facet counts from PostgreSQL for sys_* fields not stored in Qdrant."""
    query = f"""
        SELECT {storage_field}, COUNT(*) AS count
        FROM {pg.docs_table}
        WHERE {storage_field} IS NOT NULL AND {storage_field} != ''
        GROUP BY {storage_field}
        ORDER BY count DESC
    """
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return {str(row[0]): int(row[1]) for row in cur.fetchall()}


# A storage column name must be a plain SQL identifier before it can be
# interpolated (values are always parameterised). Storage fields come from the
# config-derived field mapping, never raw user input.
_SAFE_PG_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def doc_ids_from_pg_field(
    pg, storage_field: str, values: List[str], limit: int = 50000
) -> List[str]:
    """doc_ids whose ``sys_*`` column matches any of the given values.

    Counterpart to :func:`build_facets_from_pg` — used so document search
    resolves PostgreSQL-sourced fields (e.g. ``sys_language``) the same way
    their facet counts are computed, instead of filtering the Qdrant document
    payload (which does not carry these fields).
    """
    vals = [v for v in values if v]
    if not vals or not _SAFE_PG_FIELD_RE.match(storage_field):
        return []
    query = f"""
        SELECT doc_id
        FROM {pg.docs_table}
        WHERE {storage_field} = ANY(%s)
        LIMIT %s
    """
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (vals, limit))
            return [str(row[0]) for row in cur.fetchall()]


def doc_ids_from_pg_jsonb(
    pg, raw_key: str, values: List[str], limit: int = 50000
) -> List[str]:
    """doc_ids whose ``src_doc_raw_metadata->>raw_key`` matches any given value.

    Counterpart to :func:`build_facets_from_pg_jsonb`. ``raw_key`` comes from
    the trusted ``src_field_mapping`` config and is passed as a parameter.
    """
    vals = [v for v in values if v]
    if not vals:
        return []
    query = f"""
        SELECT doc_id
        FROM {pg.docs_table}
        WHERE src_doc_raw_metadata->>%s = ANY(%s)
        LIMIT %s
    """
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (raw_key, vals, limit))
            return [str(row[0]) for row in cur.fetchall()]


def count_src_jsonb_field_for_doc_ids(pg, raw_key: str, doc_ids: List[str]) -> Counter:
    """Count distinct values of ``src_doc_raw_metadata->>raw_key`` across a
    specific set of docs.

    Used by query-narrowed faceting on ``src_*`` fields whose values live
    only in the JSONB raw-metadata column (the Qdrant chunk payload only
    sometimes carries the field, so per-payload aggregation under-counts).
    ``raw_key`` must come from the trusted ``src_field_mapping`` config and
    is passed as a parameter, not interpolated.
    """
    if not doc_ids:
        return Counter()
    placeholders = ", ".join(["%s"] * len(doc_ids))
    sql = f"""
        SELECT src_doc_raw_metadata->>%s
        FROM {pg.docs_table}
        WHERE doc_id IN ({placeholders})
    """
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [raw_key, *doc_ids])
            rows = cur.fetchall()
    return Counter(row[0] for row in rows if row[0] not in (None, ""))


def count_sys_field_for_doc_ids(pg, sys_field: str, doc_ids: List[str]) -> Counter:
    """Count distinct values of a ``sys_*`` column across a set of docs.

    ``sys_field`` is a column name and is validated against an allowlist
    before interpolation to prevent SQL injection.
    """
    if not doc_ids:
        return Counter()
    if not sys_field.startswith("sys_") or not sys_field.replace("_", "").isalnum():
        raise ValueError(f"Invalid sys_field column: {sys_field!r}")
    placeholders = ", ".join(["%s"] * len(doc_ids))
    sql = f"""
        SELECT {sys_field}
        FROM {pg.docs_table}
        WHERE doc_id IN ({placeholders})
    """
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, doc_ids)
            rows = cur.fetchall()
    return Counter(row[0] for row in rows if row[0] not in (None, ""))


def build_facets_from_pg_jsonb(pg, raw_key: str) -> Dict[str, int]:
    """Get facet counts for src_* fields stored inside src_doc_raw_metadata.

    The Qdrant payload only carries fields that the indexer copied as
    top-level keys; raw metadata read from the source (e.g. WFP's
    ``"Evaluation category"`` column) lives only in the ``src_doc_raw_metadata``
    JSONB blob in PostgreSQL. ``raw_key`` is the original source key
    (passed as a query parameter, never interpolated) and must come from
    the ``src_field_mapping`` in config.json.
    """
    query = f"""
        SELECT src_doc_raw_metadata->>%s AS value, COUNT(*) AS count
        FROM {pg.docs_table}
        WHERE src_doc_raw_metadata->>%s IS NOT NULL
          AND src_doc_raw_metadata->>%s != ''
        GROUP BY value
        ORDER BY count DESC
    """
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (raw_key, raw_key, raw_key))
            return {str(row[0]): int(row[1]) for row in cur.fetchall()}


def _is_dynamic_field(core_field: str) -> bool:
    """Return True for config-driven fields that need cardinality validation."""
    return core_field.startswith("src_") or core_field.startswith("tag_")


def _validate_and_route_field(
    core_field: str,
    raw_counts: Dict[Any, int],
    facets_result: Dict[str, List[FacetValue]],
    range_fields: Dict[str, RangeInfo],
) -> None:
    """Validate cardinality for dynamic fields and route to facets or range_fields.

    For ``src_*`` / ``tag_*`` fields:
    - If all values are numerical → store min/max in ``range_fields``.
    - If non-numerical and unique count > ``FILTER_FIELD_MAX_UNIQUE_VALS`` → raise.
    - Otherwise → build normal facet list.

    Core fields (without ``src_`` / ``tag_`` prefix) are always treated as normal
    facets with no cardinality limit.
    """
    if _is_dynamic_field(core_field):
        # Filter out empty keys for counting
        non_empty = {k: v for k, v in raw_counts.items() if k not in (None, "")}
        if _all_values_numerical(non_empty):
            if non_empty:
                range_fields[core_field] = _build_range_info(non_empty)
            else:
                facets_result[core_field] = []
            return

        if len(non_empty) > FILTER_FIELD_MAX_UNIQUE_VALS:
            raise ValueError(
                f"Filter field '{core_field}' has {len(non_empty)} unique values "
                f"(max {FILTER_FIELD_MAX_UNIQUE_VALS}). Remove it from filter_fields "
                f"in config.json or reduce the field's cardinality."
            )

    facets_result[core_field] = build_generic_facets(raw_counts)


def _facet_tag_field(db, core_field: str) -> Dict[Any, int]:
    """Query facet counts for a tag_* field from the chunks collection."""
    if not hasattr(db, "facet"):
        return {}
    return db.facet(
        collection_name=db.chunks_collection,
        key=core_field,
        filter_conditions=None,
        limit=2000,
        exact=False,
    )


def _facet_storage_field(
    db,
    pg,
    core_field: str,
    storage_field: str,
    facet_filter,
    src_field_mapping: Optional[Dict[str, str]] = None,
) -> Dict[Any, int]:
    """Query facet counts for a storage field from Qdrant or PostgreSQL.

    Routing:
    - ``sys_*`` fields → PostgreSQL top-level columns (when ``pg`` is provided).
    - ``src_*`` fields with a configured ``src_field_mapping`` entry →
      PostgreSQL ``src_doc_raw_metadata`` JSONB lookup.
    - Everything else → Qdrant payload facet (with ``facet_filter`` applied).
    """
    if storage_field.startswith("sys_") and pg:
        return build_facets_from_pg(pg, storage_field)
    if storage_field.startswith("src_") and pg and src_field_mapping:
        raw_key = src_field_mapping.get(storage_field)
        if raw_key:
            return build_facets_from_pg_jsonb(pg, raw_key)
    return db.facet_documents(
        key=storage_field,
        filter_conditions=facet_filter,
        limit=2000,
        exact=False,
    )


def _safe_facet_query(query_fn, core_field: str) -> Optional[Dict[Any, int]]:
    """Run a facet query, returning None on failure."""
    try:
        return query_fn()
    except Exception as exc:
        logger.warning("Facet query failed for %s: %s", core_field, exc)
        return None


def build_facets_from_db(
    db,
    filter_fields_config: Dict[str, str],
    facet_filter,
    resolve_storage_field,
    pg=None,
    src_field_mapping: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, List[FacetValue]], Dict[str, RangeInfo]]:
    """Build facet results for all filter fields.

    Routes sys_* fields to PostgreSQL and all others to Qdrant.
    Maps language codes to full display names.
    Detects numerical dynamic fields and returns them as range_fields.
    When ``src_field_mapping`` is provided, ``src_*`` fields with a configured
    raw key are read from the ``src_doc_raw_metadata`` JSONB column.

    Returns:
        Tuple of (facets dict, range_fields dict).

    Raises:
        ValueError: If a non-numerical src_*/tag_* field exceeds
            FILTER_FIELD_MAX_UNIQUE_VALS unique values.
    """
    facets_result: Dict[str, List[FacetValue]] = {}
    range_fields: Dict[str, RangeInfo] = {}

    for core_field in filter_fields_config.keys():
        if core_field == "title":
            facets_result[core_field] = []
            continue

        raw_counts = _get_raw_counts(
            db,
            pg,
            core_field,
            facet_filter,
            resolve_storage_field,
            src_field_mapping=src_field_mapping,
        )
        if raw_counts is None:
            facets_result[core_field] = []
            continue

        if core_field == "language":
            raw_counts = {LANGUAGE_NAMES.get(k, k): v for k, v in raw_counts.items()}

        if core_field == "published_year":
            facets_result[core_field] = build_year_facets(raw_counts)
            continue

        _validate_and_route_field(core_field, raw_counts, facets_result, range_fields)

    return facets_result, range_fields


def _get_raw_counts(
    db,
    pg,
    core_field,
    facet_filter,
    resolve_storage_field,
    src_field_mapping: Optional[Dict[str, str]] = None,
):
    """Fetch raw facet counts for a field, returning None on failure."""
    if core_field.startswith("tag_"):
        return _safe_facet_query(lambda: _facet_tag_field(db, core_field), core_field)

    storage_field = resolve_storage_field(core_field, db.data_source if db else None)
    return _safe_facet_query(
        lambda: _facet_storage_field(
            db,
            pg,
            core_field,
            storage_field,
            facet_filter,
            src_field_mapping=src_field_mapping,
        ),
        core_field,
    )
