"""Helpers for building and resolving filter fields used by search routes."""

from typing import Any, Dict, List, Optional, Set, Union

from qdrant_client.http import models

from pipeline.db import (
    get_default_filter_fields,
    get_field_mapping,
    get_src_field_mapping,
    get_taxonomy_filter_fields,
    resolve_data_source,
)
from ui.backend.utils.document_utils import map_core_field_to_storage
from ui.backend.utils.facet_helpers import (
    doc_ids_from_pg_jsonb,
    expand_multivalue_filter,
)
from ui.backend.utils.language_codes import LANGUAGE_CODES

FILTER_VALUE_SEPARATOR = ","
FILTER_VALUE_ESCAPE = "\\"


def _split_escaped_values(text: str) -> List[str]:
    """Split one filter string into its values.

    Values are separated by commas. ``\\,`` is a comma inside a value and
    ``\\\\`` a backslash; any other backslash is kept as written, so values
    without commas or backslashes read exactly as before.
    """
    values: List[str] = []
    current: List[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if char == FILTER_VALUE_ESCAPE and following in (
            FILTER_VALUE_SEPARATOR,
            FILTER_VALUE_ESCAPE,
        ):
            current.append(following)
            index += 2
            continue
        if char == FILTER_VALUE_SEPARATOR:
            values.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    values.append("".join(current))
    return values


def parse_filter_values(value: Any) -> List[Any]:
    """Return the values a filter selects.

    A filter arrives either as a list of values or as one string listing them
    separated by commas, with ``\\,`` for a comma inside a value and ``\\\\``
    for a backslash (see :func:`_split_escaped_values`). This is the only place
    a filter string is split, so names that contain commas (``SDG16 - Peace,
    Justice and Strong Institutions``) are never cut in two. Values are
    stripped and blanks dropped. A number or other non-string scalar is one
    value, kept as it is.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if item is not None]
        return [item for item in items if item]
    if not isinstance(value, str):
        return [value]
    parts = (part.strip() for part in _split_escaped_values(value))
    return [part for part in parts if part]


def filter_match(value: Any) -> Union[models.MatchAny, models.MatchValue]:
    """Qdrant match for a filter: ``MatchValue`` for one value, ``MatchAny``
    for several (values OR within a field).

    Raises:
        ValueError: If the filter selects no value.
    """
    values = parse_filter_values(value)
    if not values:
        raise ValueError(f"Filter value selects nothing: {value!r}")
    if len(values) == 1:
        return models.MatchValue(value=values[0])
    return models.MatchAny(any=values)


def normalize_language_filter(language: Any) -> Optional[List[str]]:
    """Convert the selected language name(s) to codes for DB queries."""
    names = parse_filter_values(language)
    if not names:
        return None
    return [LANGUAGE_CODES.get(name, name) for name in names]


def resolve_storage_field(core_field: str, data_source: Optional[str]) -> str:
    """Map a core filter field name to the Qdrant storage field."""
    if core_field != "language":
        return map_core_field_to_storage(core_field)
    source = resolve_data_source(data_source)
    field_mapping = get_field_mapping(source)
    if field_mapping.get("language") == "sys_language":
        return "sys_language"
    return map_core_field_to_storage(core_field)


def build_core_filters_from_params(
    organization: Optional[str],
    title: Optional[str],
    published_year: Optional[str],
    document_type: Optional[str],
    country: Optional[str],
    language: Optional[str],
) -> Dict[str, Any]:
    """Build initial core_filters dict from route query parameters."""
    return {
        "organization": organization,
        "title": title,
        "published_year": published_year,
        "document_type": document_type,
        "country": country,
        "language": normalize_language_filter(language),
    }


def collect_range_bounds(
    core_filters: Dict[str, Any], data_source: Optional[str]
) -> Dict[str, Dict[str, float]]:
    """Extract _min/_max params into {storage_field: {gte/lte: val}}."""
    bounds: Dict[str, Dict[str, float]] = {}
    for core_field, value in core_filters.items():
        if not value:
            continue
        if core_field.endswith("_min"):
            sf = resolve_storage_field(core_field[:-4], data_source)
            bounds.setdefault(sf, {})["gte"] = float(value)
        elif core_field.endswith("_max"):
            sf = resolve_storage_field(core_field[:-4], data_source)
            bounds.setdefault(sf, {})["lte"] = float(value)
    return bounds


def build_needed_fields(
    filter_fields_config: Dict[str, str], data_source: Optional[str]
) -> List[str]:
    """Build the list of Qdrant storage fields needed for facet counting."""
    needed_fields = [
        resolve_storage_field(core_field, data_source)
        for core_field in filter_fields_config.keys()
        if core_field != "title"
    ]
    return list(set(needed_fields))


def add_dynamic_filters(
    core_filters: Dict,
    query_params,
    data_source: Optional[str] = None,
) -> None:
    """Pick up config-driven filter params (src_*, tag_*, etc.) dynamically."""
    source = resolve_data_source(data_source)
    filter_fields = {
        **get_default_filter_fields(source),
        **get_taxonomy_filter_fields(source),
    }
    hardcoded = {
        "organization",
        "title",
        "published_year",
        "document_type",
        "country",
        "language",
    }
    for name, value in query_params.items():
        if not value:
            continue
        if name.endswith("_min") or name.endswith("_max"):
            base = name[:-4]
            if base in filter_fields and base not in hardcoded:
                core_filters[name] = value
        elif name in filter_fields and name not in hardcoded:
            core_filters[name] = value


def build_doc_id_filter(value: Any) -> models.Filter:
    """Build a nested OR filter matching doc_id or sys_doc_id."""
    match = filter_match(value)
    return models.Filter(
        should=[
            models.FieldCondition(key="doc_id", match=match),
            models.FieldCondition(key="sys_doc_id", match=match),
        ]
    )


def collect_range_conditions(
    filters: dict,
) -> List[models.FieldCondition]:
    """Collect _min/_max params into Range conditions."""
    bounds: Dict[str, Dict[str, float]] = {}
    for field, value in filters.items():
        if field.endswith("_min"):
            bounds.setdefault(field[:-4], {})["gte"] = float(value)
        elif field.endswith("_max"):
            bounds.setdefault(field[:-4], {})["lte"] = float(value)
    return [
        models.FieldCondition(key=sf, range=models.Range(**b))
        for sf, b in bounds.items()
    ]


# Sentinel doc_id used when a document filter resolves to no documents, so the
# search returns nothing rather than falling back to an unfiltered run.
NO_MATCH_DOC_ID = "00000000-0000-0000-0000-000000000000"


def _normalize_doc_titles(value: Any) -> List[str]:
    """Coerce a ``doc_titles`` filter value into a clean list of titles.

    Accepts a list of strings, or one filter string of comma-separated titles
    (see :func:`parse_filter_values`; a comma inside a title is ``\\,``).
    Blank entries are dropped.

    Raises:
        ValueError: If the value is neither a string nor a list/tuple.
    """
    if not isinstance(value, (str, list, tuple)):
        raise ValueError("doc_titles must be a list of document titles")
    return parse_filter_values(value)


def _existing_doc_id_set(value: Any) -> Optional[Set[str]]:
    """Return the set of doc_ids already present in a filter value, or None."""
    if value is None:
        return None
    if not isinstance(value, (str, list, tuple)):
        return set()
    return {str(part) for part in parse_filter_values(value)}


# Doc-level filters resolved to a doc_id set for the harness chunk search.
# ``src_*`` fields (from the data source's ``src_field_mapping``) are detected
# dynamically in :func:`_is_doc_level_key`.
_DOC_LEVEL_FILTER_KEYS = ("doc_titles", "region", "language")


def _is_doc_level_key(key: str, src_mapping: Dict[str, str]) -> bool:
    """True when a filter key must be resolved to doc_ids for the chunk search."""
    return key in _DOC_LEVEL_FILTER_KEYS or key in src_mapping


def _title_doc_ids(value: Any, pg) -> Optional[Set[str]]:
    """Resolve a ``doc_titles`` value to a doc_id set (None if no titles)."""
    if value is None:
        return None
    titles = _normalize_doc_titles(value)
    if not titles:
        return None
    return set(pg.fetch_doc_ids_by_exact_titles(titles))


def _region_names(value: Any) -> List[str]:
    """Coerce a ``region`` filter value into a list of region names.

    Region names often contain commas, so a string is read with
    :func:`parse_filter_values`: a comma inside a name is ``\\,``. Blank entries
    are dropped.

    Raises:
        ValueError: If the value is neither a string nor a list/tuple.
    """
    if not isinstance(value, (str, list, tuple)):
        raise ValueError("region must be a string or a list of region names")
    return parse_filter_values(value)


def _region_doc_ids(value: Any, pg) -> Optional[Set[str]]:
    """Resolve a ``region`` value to the union of matching doc_ids (None if empty).

    Region is a document-level field (not stamped on chunks), so the selected
    region names are resolved to the documents listing any of them via
    ``pg.fetch_doc_ids_by_region`` (OR within the region facet).
    """
    if value is None:
        return None
    names = _region_names(value)
    if not names:
        return None
    return set(pg.fetch_doc_ids_by_region(names))


def _language_names(value: Any) -> List[str]:
    """Coerce a ``language`` filter value into a list of language names/codes.

    Accepts a list of strings, or one comma-separated filter string (see
    :func:`parse_filter_values`). Blank entries are dropped.

    Raises:
        ValueError: If the value is neither a string nor a list/tuple.
    """
    if not isinstance(value, (str, list, tuple)):
        raise ValueError("language must be a string or a list of languages")
    return parse_filter_values(value)


def _language_doc_ids(value: Any, pg) -> Optional[Set[str]]:
    """Resolve a ``language`` value to a doc_id set (None if empty).

    Language lives on documents (``sys_language``), not on chunks, so it is
    resolved via PostgreSQL exactly like the ``/search`` route does. Values may
    be full language names (as faceted in the UI) or ISO codes; names are
    normalised to codes first.
    """
    if value is None:
        return None
    names = _language_names(value)
    if not names:
        return None
    codes = [LANGUAGE_CODES.get(name, name) for name in names]
    return set(pg.fetch_doc_ids_by_language(codes))


def _src_field_values(field: str, value: Any) -> List[str]:
    """Coerce a ``src_*`` filter value into a list of values, reading a string
    with :func:`parse_filter_values` as the search route does.

    Raises:
        ValueError: If the value is neither a string nor a list/tuple.
    """
    if not isinstance(value, (str, list, tuple)):
        raise ValueError(f"{field} must be a string or a list of values")
    return parse_filter_values(value)


def _pop_src_field_constraints(
    result: Dict[str, Any], src_mapping: Dict[str, str], pg
) -> List[Set[str]]:
    """Pop each present ``src_*`` filter and resolve it to a doc_id set.

    ``src_*`` values live in the ``docs.src_doc_raw_metadata`` JSONB (only
    sparsely stamped onto chunks), so each field is resolved via PostgreSQL —
    the same source its facet counts come from. Values OR within a field; the
    returned sets AND across fields.
    """
    constraints: List[Set[str]] = []
    for field, raw_key in src_mapping.items():
        if field not in result:
            continue
        values = _src_field_values(field, result.pop(field))
        if values:
            constraints.append(set(doc_ids_from_pg_jsonb(pg, raw_key, values)))
    return constraints


def resolve_doc_level_filters(
    filters: Dict[str, Any], pg, data_source: str
) -> Dict[str, Any]:
    """Resolve document-level filters to a ``doc_id`` filter for the harness.

    The eval harness calls the chunk search directly and so bypasses the search
    route's own resolvers. Filter fields whose values live on documents rather
    than chunks — ``doc_titles`` (exact UI titles), ``region``, ``language`` and
    the data source's config-declared ``src_*`` fields — must therefore be
    resolved to doc_ids at run time, mirroring the ``/search`` route. Each
    resolved set is AND-combined with any existing ``doc_id`` filter (values OR
    within a field). When the combination matches nothing, the filter is pinned
    to :data:`NO_MATCH_DOC_ID` so the run returns no results (never unfiltered).

    Chunk-resident fields (``country``, ``document_type``, ``organization``,
    year ranges, taxonomy ``tag_*`` fields, …) are intentionally left untouched:
    the chunk search applies them natively as payload filters.

    Args:
        filters: Case ``filters`` dict. Not mutated; a new dict is returned.
        pg: Postgres client for the case's data source.
        data_source: Data source key, used to look up its ``src_field_mapping``.

    Returns:
        A new filters dict with resolved keys replaced by a ``doc_id`` filter, or
        the original dict when there is nothing document-level to resolve.
    """
    if not isinstance(filters, dict):
        return filters
    src_mapping = get_src_field_mapping(data_source) or {}
    if not any(_is_doc_level_key(key, src_mapping) for key in filters):
        return filters
    result = dict(filters)
    constraints: List[Set[str]] = []
    existing = _existing_doc_id_set(result.get("doc_id"))
    if existing is not None:
        constraints.append(existing)
    for resolved in (
        _title_doc_ids(result.pop("doc_titles", None), pg),
        _region_doc_ids(result.pop("region", None), pg),
        _language_doc_ids(result.pop("language", None), pg),
    ):
        if resolved is not None:
            constraints.append(resolved)
    constraints.extend(_pop_src_field_constraints(result, src_mapping, pg))
    if not constraints:
        return result
    resolved_ids = set.intersection(*constraints)
    result["doc_id"] = sorted(resolved_ids) if resolved_ids else [NO_MATCH_DOC_ID]
    return result


# Core fields whose stored values are never "; "-joined, or that are resolved
# to a doc_id constraint elsewhere, so multi-value expansion skips them.
_MULTIVALUE_EXPANSION_SKIP = frozenset(
    {"title", "doc_id", "language", "region", "published_year"}
)


def _is_expandable_filter(core_field: str, value: Any) -> bool:
    """True for keyword payload filters whose stored values may be "; "-joined."""
    if not isinstance(value, str) or not value.strip():
        return False
    if core_field in _MULTIVALUE_EXPANSION_SKIP:
        return False
    if core_field.startswith(("src_", "tag_")):
        return False
    return not core_field.endswith(("_min", "_max"))


def expand_multivalue_filters(
    db, core_filters: Dict[str, Any], data_source: Optional[str]
) -> None:
    """Expand keyword filters in place so "; "-joined payload values match.

    Multi-valued document fields (country, theme, topic, …) are stored as one
    ``"; "``-joined string (``"Kenya; Ethiopia"``) and faceted as individual
    values, but a payload filter matches the whole string exactly, so selecting
    ``Kenya`` misses every multi-country document. For each keyword filter this
    adds the raw joined values that contain a selected value (see
    :func:`expand_multivalue_filter`), turning the filter into a list that the
    query builders apply as ``MatchAny``. A filter that gains nothing is left
    untouched so single values keep their exact match.

    The expansion reads the field's values through a Qdrant facet query, which
    Qdrant only serves for indexed payload fields, so fields without an index in
    the documents collection keep their exact match instead of failing the
    whole search (e.g. ``map_topic`` on sources that never index it).
    """
    indexed_keys: Optional[Set[str]] = None
    for core_field, value in list(core_filters.items()):
        if not _is_expandable_filter(core_field, value):
            continue
        if indexed_keys is None:
            indexed_keys = db.indexed_payload_keys(db.documents_collection)
        storage_field = resolve_storage_field(core_field, data_source)
        if storage_field not in indexed_keys:
            continue
        selected = parse_filter_values(value)
        expanded = expand_multivalue_filter(db, storage_field, selected)
        if len(expanded) > len(selected):
            core_filters[core_field] = sorted(expanded)
