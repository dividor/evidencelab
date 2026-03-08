"""Helpers for building and resolving filter fields used by search routes."""

from typing import Any, Dict, List, Optional

from qdrant_client.http import models

from pipeline.db import (
    get_default_filter_fields,
    get_field_mapping,
    get_taxonomy_filter_fields,
)
from ui.backend.utils.document_utils import map_core_field_to_storage
from ui.backend.utils.language_codes import LANGUAGE_CODES


def normalize_language_filter(language: Optional[str]) -> Optional[str]:
    """Convert full language name(s) back to codes for DB queries."""
    if not language:
        return None
    parts = [v.strip() for v in language.split(",") if v.strip()]
    mapped = [LANGUAGE_CODES.get(p, p) for p in parts]
    return ",".join(mapped)


def resolve_storage_field(core_field: str, data_source: Optional[str]) -> str:
    """Map a core filter field name to the Qdrant storage field."""
    if core_field != "language":
        return map_core_field_to_storage(core_field)
    source = data_source or "uneg"
    field_mapping = get_field_mapping(source)
    if field_mapping.get("language") == "sys_language":
        return "sys_language"
    return map_core_field_to_storage(core_field)


def split_filter_values(value: Any) -> Optional[List[str]]:
    """Split a comma-separated filter value into a list, or return None."""
    if isinstance(value, str) and "," in value:
        values = [item.strip() for item in value.split(",") if item.strip()]
        if values:
            return values
    return None


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
    source = data_source or "uneg"
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


def build_doc_id_filter(value, as_multi_values_fn) -> models.Filter:
    """Build a nested OR filter matching doc_id or sys_doc_id."""
    multi_values = as_multi_values_fn(value)
    match = (
        models.MatchAny(any=multi_values)
        if multi_values
        else models.MatchValue(value=value)
    )
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
