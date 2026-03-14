"""Helpers for building facet results from Qdrant and PostgreSQL."""

import logging
from collections import Counter
from typing import Any, Dict, List, Tuple

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


def _split_multivalue(raw_value: str) -> List[str]:
    """Split a multi-value string on '; ' or ',' separators."""
    if "; " in raw_value:
        return [p.strip() for p in raw_value.split("; ") if p.strip()]
    if "," in raw_value:
        return [p.strip() for p in raw_value.split(",") if p.strip()]
    return []


def build_generic_facets(raw_counts: Dict[Any, int]) -> List[FacetValue]:
    counter: Counter[str] = Counter()
    for raw_value, count in raw_counts.items():
        if raw_value is None or raw_value == "":
            continue
        if isinstance(raw_value, str):
            parts = _split_multivalue(raw_value)
            if parts:
                for item in parts:
                    counter[item] += count
                continue
        counter[str(raw_value)] += count
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
        if "; " in raw_str:
            parts = {p.strip() for p in raw_str.split("; ")}
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
    db, pg, core_field: str, storage_field: str, facet_filter
) -> Dict[Any, int]:
    """Query facet counts for a storage field from Qdrant or PostgreSQL."""
    if storage_field.startswith("sys_") and pg:
        return build_facets_from_pg(pg, storage_field)
    return db.facet_documents(
        key=storage_field,
        filter_conditions=facet_filter,
        limit=2000,
        exact=False,
    )


def _safe_facet_query(query_fn, core_field: str) -> Dict[Any, int]:
    """Run a facet query, returning empty dict on failure."""
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
) -> Tuple[Dict[str, List[FacetValue]], Dict[str, RangeInfo]]:
    """Build facet results for all filter fields.

    Routes sys_* fields to PostgreSQL and all others to Qdrant.
    Maps language codes to full display names.
    Detects numerical dynamic fields and returns them as range_fields.

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
            db, pg, core_field, facet_filter, resolve_storage_field
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


def _get_raw_counts(db, pg, core_field, facet_filter, resolve_storage_field):
    """Fetch raw facet counts for a field, returning None on failure."""
    if core_field.startswith("tag_"):
        return _safe_facet_query(lambda: _facet_tag_field(db, core_field), core_field)

    storage_field = resolve_storage_field(core_field, db.data_source if db else None)
    return _safe_facet_query(
        lambda: _facet_storage_field(db, pg, core_field, storage_field, facet_filter),
        core_field,
    )
