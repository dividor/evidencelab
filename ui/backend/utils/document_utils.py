import re
from typing import Any, Dict

CORE_FIELD_MAP = {
    "organization": "map_organization",
    "document_type": "map_document_type",
    "published_year": "map_published_year",
    "title": "map_title",
    "language": "map_language",
    "country": "map_country",
    "region": "map_region",
    "theme": "map_theme",
    "pdf_url": "map_pdf_url",
    "report_url": "map_report_url",
}

SYSTEM_FIELD_MAP = {
    "status": "sys_status",
    "filepath": "sys_filepath",
    "parsed_folder": "sys_parsed_folder",
    "metadata_checksum": "sys_metadata_checksum",
    "file_checksum": "sys_file_checksum",
    "stages": "sys_stages",
    "page_count": "sys_page_count",
    "word_count": "sys_word_count",
    "language": "sys_language",
    "file_format": "sys_file_format",
    "file_size_mb": "sys_file_size_mb",
    "pipeline_elapsed_seconds": "sys_pipeline_elapsed_seconds",
    "summarization_method": "sys_summarization_method",
    "full_summary": "sys_full_summary",
    "toc": "sys_toc",
    "toc_classified": "sys_toc_classified",
    "user_edited_section_types": "sys_user_edited_section_types",
    "toc_approved": "sys_toc_approved",
    "error_message": "sys_error_message",
    "taxonomies": "sys_taxonomies",
}


def normalize_document_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Expose core/system fields without prefixes while keeping prefixed fields."""
    normalized = dict(payload)
    for core_field, map_key in CORE_FIELD_MAP.items():
        if map_key in payload:
            normalized[core_field] = payload[map_key]
    for system_field, sys_key in SYSTEM_FIELD_MAP.items():
        if sys_key in payload:
            normalized[system_field] = payload[sys_key]
    # Unpack src_doc_raw_metadata into individual src_* top-level keys.
    # Raw keys are human-readable (e.g. "Evaluation category") so we
    # sanitize them to snake_case with src_ prefix.
    raw_meta = payload.get("src_doc_raw_metadata")
    if isinstance(raw_meta, dict):
        for key, value in raw_meta.items():
            sanitized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            src_key = (
                f"src_{sanitized}" if not sanitized.startswith("src_") else sanitized
            )
            normalized.setdefault(src_key, value)
    return normalized


def map_core_field_to_storage(field: str) -> str:
    return CORE_FIELD_MAP.get(field, field)
