from __future__ import annotations

import json
from typing import Any, Dict, List


def _parse_sys_stages(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return value


def _get_sys_value(
    target_key: str, sys_data: Dict[str, Any], source_keys: List[str]
) -> Any:
    for source_key in source_keys:
        if source_key in sys_data:
            value = sys_data.get(source_key)
            if target_key == "sys_stages":
                return _parse_sys_stages(value)
            return value
    return None


def merge_sys_data_fields(documents: List[Dict[str, Any]]) -> None:
    if not documents:
        return
    field_sources = {
        "sys_full_summary": [
            "sys_full_summary",
            "full_summary",
            "summary",
            "sys_summary",
        ],
        "sys_language": ["sys_language", "language", "src_language"],
        "sys_file_format": ["sys_file_format", "file_format", "format"],
        "sys_page_count": ["sys_page_count", "page_count", "total_pages"],
        "sys_file_size_mb": ["sys_file_size_mb", "file_size_mb"],
        "sys_error_message": [
            "sys_error_message",
            "sys_download_error",
            "error_message",
            "sys_error",
            "error",
        ],
        "sys_toc": ["sys_toc", "toc"],
        "sys_toc_classified": ["sys_toc_classified", "toc_classified"],
        "sys_status": ["sys_status", "status"],
        "sys_stages": ["sys_stages", "stages"],
        "sys_status_timestamp": ["sys_status_timestamp"],
    }
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        sys_data = doc.get("sys_data")
        if not isinstance(sys_data, dict):
            continue
        for target_key, source_keys in field_sources.items():
            if target_key in doc:
                continue
            value = _get_sys_value(target_key, sys_data, source_keys)
            if value is not None:
                doc[target_key] = value


def merge_sys_data_for_doc(doc: Dict[str, Any]) -> None:
    if not isinstance(doc, dict):
        return
    sys_data = doc.get("sys_data")
    if not isinstance(sys_data, dict):
        return
    if "sys_toc_classified" in sys_data:
        doc.setdefault("sys_toc_classified", sys_data.get("sys_toc_classified"))
    if "sys_toc" in sys_data:
        doc.setdefault("sys_toc", sys_data.get("sys_toc"))
    if "sys_page_count" in sys_data:
        doc.setdefault("sys_page_count", sys_data.get("sys_page_count"))
