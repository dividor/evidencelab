"""Helpers for building facet results from Qdrant and PostgreSQL."""

from collections import Counter
from typing import Any, Dict, List

from ui.backend.schemas import FacetValue
from ui.backend.utils.language_codes import LANGUAGE_NAMES


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


def build_facets_from_db(
    db,
    filter_fields_config: Dict[str, str],
    facet_filter,
    resolve_storage_field,
    pg=None,
) -> Dict[str, List[FacetValue]]:
    """Build facet results for all filter fields.

    Routes sys_* fields to PostgreSQL and all others to Qdrant.
    Maps language codes to full display names.
    """
    facets_result: Dict[str, List[FacetValue]] = {}
    for core_field in filter_fields_config.keys():
        if core_field == "title":
            facets_result[core_field] = []
            continue

        # Taxonomy tag fields live on chunks, not documents
        if core_field.startswith("tag_"):
            if not hasattr(db, "facet"):
                facets_result[core_field] = []
                continue
            raw_counts = db.facet(
                collection_name=db.chunks_collection,
                key=core_field,
                filter_conditions=None,
                limit=2000,
                exact=False,
            )
            facets_result[core_field] = [
                FacetValue(value=str(v), count=c)
                for v, c in sorted(raw_counts.items(), key=lambda x: -x[1])
                if v not in (None, "")
            ]
            continue

        storage_field = resolve_storage_field(
            core_field, db.data_source if db else None
        )

        # sys_* fields live in PostgreSQL, not Qdrant
        if storage_field.startswith("sys_") and pg:
            raw_counts = build_facets_from_pg(pg, storage_field)
        else:
            raw_counts = db.facet_documents(
                key=storage_field,
                filter_conditions=facet_filter,
                limit=2000,
                exact=False,
            )

        # Map language codes to full names
        if core_field == "language":
            raw_counts = {LANGUAGE_NAMES.get(k, k): v for k, v in raw_counts.items()}

        if core_field == "published_year":
            facets_result[core_field] = build_year_facets(raw_counts)
            continue

        facets_result[core_field] = build_generic_facets(raw_counts)

    return facets_result
