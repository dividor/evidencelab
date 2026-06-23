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


# ---------------------------------------------------------------------------
# Filter-aware corpus facets (query-independent)
#
# These build facet counts directly from the Postgres docs table so the
# search sidebar always shows how many *documents* fall under each value,
# given the user's other active filters. The counts never depend on the
# search query, so running a search no longer changes the numbers.
#
# "Exclude-self" semantics: a field's own selection does not constrain its
# own value list, so multi-select within a dimension stays usable (e.g.
# picking one country does not zero out the other countries).
#
# Known, intentional limitations (NOT silent fallbacks):
#   * tag_* filters and numeric _min/_max range filters are not applied as
#     constraints here — tag values live in the chunks collection, not the
#     docs table. tag_* facet *counts* are still produced via the existing
#     Qdrant chunk facet path so their display is unchanged.
# ---------------------------------------------------------------------------

_MULTI_VALUE_SEPARATORS = ("; ", " | ")


def _is_safe_identifier(name: str) -> bool:
    """Return True if *name* is a safe SQL identifier (alphanumerics + ``_``)."""
    return bool(name) and name.replace("_", "").isalnum()


def _split_selected_values(value: Any) -> List[str]:
    """Split a comma-separated filter value into a clean list of strings."""
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _facet_column_expr(
    core_field: str,
    storage_field: str,
    src_field_mapping: Optional[Dict[str, str]],
) -> Tuple[str, List[Any]]:
    """Resolve a field to a ``(sql_expression, params)`` pair on the docs table.

    ``src_*`` fields map to a ``src_doc_raw_metadata->>key`` JSONB lookup with
    the raw key bound as a parameter (never interpolated). Every other field
    maps to a validated physical column name.
    """
    if core_field.startswith("src_") and src_field_mapping:
        raw_key = src_field_mapping.get(core_field) or src_field_mapping.get(
            storage_field
        )
        if raw_key:
            return "src_doc_raw_metadata->>%s", [raw_key]
    if not _is_safe_identifier(storage_field):
        raise ValueError(f"Unsafe facet column: {storage_field!r}")
    return storage_field, []


def _language_filter_values(col_expr: str, values: List[str]) -> List[str]:
    """Map ISO language codes to display names when filtering ``map_language``.

    Incoming language filters are normalised to ISO codes (``en``), but the
    ``map_language`` column stores display names (``English``); translate so
    the comparison matches.
    """
    if col_expr == "map_language":
        return [LANGUAGE_NAMES.get(v, v) for v in values]
    return values


def _value_match_sql(
    col_expr: str, col_params: List[Any], value: str
) -> Tuple[str, List[Any]]:
    """Build a multi-value-aware equality test for a single value.

    Splits stored values on ``'; '`` or ``' | '`` so a document stored as
    ``'Nepal; India'`` matches a filter on ``'Nepal'``.
    """
    clauses: List[str] = []
    params: List[Any] = []
    for sep in _MULTI_VALUE_SEPARATORS:
        clauses.append(f"%s = ANY(string_to_array({col_expr}, %s))")
        params.extend([value, *col_params, sep])
    return "(" + " OR ".join(clauses) + ")", params


def _field_filter_clause(
    core_field: str,
    col_expr: str,
    col_params: List[Any],
    values: List[str],
) -> Tuple[str, List[Any]]:
    """OR-combine value matches for one field (multi-select within a field)."""
    if core_field == "title":
        # Titles can legitimately contain the multi-value separators, so match
        # them exactly rather than splitting.
        params: List[Any] = []
        for v in values:
            params.extend([*col_params, v])
        sql = " OR ".join(f"{col_expr} = %s" for _ in values)
        return "(" + sql + ")", params
    sub_sql: List[str] = []
    params = []
    for v in values:
        clause, clause_params = _value_match_sql(col_expr, col_params, v)
        sub_sql.append(clause)
        params.extend(clause_params)
    return "(" + " OR ".join(sub_sql) + ")", params


def _is_skippable_filter(field: str, value: Any, exclude_field: Optional[str]) -> bool:
    """Return True for filters that don't constrain the docs-table query."""
    if field == exclude_field or not value:
        return True
    return field.startswith("tag_") or field.endswith("_min") or field.endswith("_max")


def _build_corpus_where(
    core_filters: Dict[str, Any],
    exclude_field: Optional[str],
    resolve_storage_field,
    data_source: Optional[str],
    src_field_mapping: Optional[Dict[str, str]],
) -> Tuple[str, List[Any]]:
    """Build a SQL ``WHERE`` fragment ANDing all active filters except *exclude_field*.

    Returns ``("", [])`` when no constraints apply. tag_* and range filters
    are intentionally skipped (see module note).
    """
    clauses: List[str] = []
    params: List[Any] = []
    for field, value in core_filters.items():
        if _is_skippable_filter(field, value, exclude_field):
            continue
        storage_field = resolve_storage_field(field, data_source)
        col_expr, col_params = _facet_column_expr(
            field, storage_field, src_field_mapping
        )
        values = _split_selected_values(value)
        if field == "language":
            values = _language_filter_values(col_expr, values)
        if not values:
            continue
        clause, clause_params = _field_filter_clause(
            field, col_expr, col_params, values
        )
        clauses.append(clause)
        params.extend(clause_params)
    return " AND ".join(clauses), params


def _corpus_field_counts(
    pg,
    core_field: str,
    storage_field: str,
    core_filters: Dict[str, Any],
    resolve_storage_field,
    data_source: Optional[str],
    src_field_mapping: Optional[Dict[str, str]],
) -> Dict[str, int]:
    """Count documents per value of *core_field*, honouring the other filters."""
    col_expr, col_params = _facet_column_expr(
        core_field, storage_field, src_field_mapping
    )
    where_sql, where_params = _build_corpus_where(
        core_filters, core_field, resolve_storage_field, data_source, src_field_mapping
    )
    inner = f"SELECT {col_expr} AS v FROM {pg.docs_table}"
    params: List[Any] = list(col_params)
    if where_sql:
        inner += f" WHERE {where_sql}"
        params.extend(where_params)
    sql = (
        f"SELECT v, COUNT(*) AS c FROM ({inner}) sub "
        "WHERE v IS NOT NULL AND v != '' GROUP BY v ORDER BY c DESC"
    )
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return {str(row[0]): int(row[1]) for row in cur.fetchall()}


def _route_corpus_counts(
    core_field: str,
    raw_counts: Dict[str, int],
    facets_result: Dict[str, List[FacetValue]],
    range_fields: Dict[str, RangeInfo],
) -> None:
    """Apply language/year shaping then route counts to facets or ranges."""
    if core_field == "language":
        raw_counts = {LANGUAGE_NAMES.get(k, k): v for k, v in raw_counts.items()}
    if core_field == "published_year":
        facets_result[core_field] = build_year_facets(raw_counts)
        return
    _validate_and_route_field(core_field, raw_counts, facets_result, range_fields)


def build_corpus_facets(
    pg,
    db,
    filter_fields_config: Dict[str, str],
    core_filters: Dict[str, Any],
    resolve_storage_field,
    data_source: Optional[str],
    src_field_mapping: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, List[FacetValue]], Dict[str, RangeInfo]]:
    """Build query-independent, filter-aware facet counts from the docs table.

    For every filter field the count reflects the documents matching all of
    the user's *other* active filters (exclude-self), so the search query
    never changes the numbers and multi-select stays usable. ``tag_*`` fields
    keep their existing chunk-based facet source.

    Returns:
        Tuple of (facets dict, range_fields dict).
    """
    facets_result: Dict[str, List[FacetValue]] = {}
    range_fields: Dict[str, RangeInfo] = {}
    for core_field in filter_fields_config.keys():
        if core_field == "title":
            facets_result[core_field] = []
            continue
        if core_field.startswith("tag_"):
            raw_counts = _safe_facet_query(
                lambda cf=core_field: _facet_tag_field(db, cf), core_field
            )
        else:
            storage_field = resolve_storage_field(core_field, data_source)
            raw_counts = _safe_facet_query(
                lambda cf=core_field, sf=storage_field: _corpus_field_counts(
                    pg,
                    cf,
                    sf,
                    core_filters,
                    resolve_storage_field,
                    data_source,
                    src_field_mapping,
                ),
                core_field,
            )
        if raw_counts is None:
            facets_result[core_field] = []
            continue
        _route_corpus_counts(core_field, raw_counts, facets_result, range_fields)
    return facets_result, range_fields
