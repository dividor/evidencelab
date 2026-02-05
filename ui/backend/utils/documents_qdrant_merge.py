from __future__ import annotations

import json
from typing import Any, Dict, List


def _merge_sys_data_toc(doc: Dict[str, Any]) -> None:
    sys_data = doc.get("sys_data")
    if not isinstance(sys_data, dict):
        return
    if not doc.get("sys_toc") and sys_data.get("sys_toc"):
        doc["sys_toc"] = sys_data.get("sys_toc")
    if not doc.get("sys_toc_classified") and sys_data.get("sys_toc_classified"):
        doc["sys_toc_classified"] = sys_data.get("sys_toc_classified")


def _needs_qdrant_payload(doc: Dict[str, Any]) -> bool:
    has_links = bool(doc.get("map_pdf_url") or doc.get("map_report_url"))
    has_toc = bool(doc.get("sys_toc") or doc.get("sys_toc_classified"))
    return not (has_links and has_toc)


def _collect_qdrant_ids(documents: List[Dict[str, Any]]) -> List[Any]:
    ids: List[Any] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        _merge_sys_data_toc(doc)
        if not _needs_qdrant_payload(doc):
            continue
        doc_id = doc.get("id") or doc.get("doc_id")
        if doc_id is not None:
            ids.append(doc_id)
    return ids


def _fetch_qdrant_payloads(db: Any, ids: List[Any]) -> Dict[str, Dict[str, Any]]:
    try:
        results = db.client.retrieve(
            collection_name=db.documents_collection,
            ids=ids,
            with_payload=True,
        )
    except Exception:
        return {}
    payload_by_id: Dict[str, Dict[str, Any]] = {}
    for result in results or []:
        payload = getattr(result, "payload", None) or {}
        if not isinstance(payload, dict):
            continue
        doc_id = getattr(result, "id", None)
        if doc_id is not None:
            payload_by_id[str(doc_id)] = payload
    return payload_by_id


def _parse_stages(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return value


def _apply_field_map(doc: Dict[str, Any], payload: Dict[str, Any]) -> None:
    field_map = {
        "map_pdf_url": "src_pdf_url",
        "map_report_url": "src_report_url",
        "sys_full_summary": "sys_full_summary",
        "sys_language": "src_language",
        "sys_file_format": "src_file_format",
        "sys_page_count": "src_page_count",
        "sys_error_message": "sys_error_message",
        "sys_stages": "sys_stages",
    }
    for target_key, source_key in field_map.items():
        if doc.get(target_key):
            continue
        value = payload.get(source_key)
        if value is not None:
            if target_key == "sys_stages":
                value = _parse_stages(value)
            doc[target_key] = value


def _apply_toc(doc: Dict[str, Any], payload: Dict[str, Any]) -> None:
    if not doc.get("sys_toc"):
        toc = (
            payload.get("sys_toc")
            or payload.get("toc")
            or payload.get("toc_classified")
        )
        if toc:
            doc["sys_toc"] = toc


def _apply_file_size(doc: Dict[str, Any], payload: Dict[str, Any]) -> None:
    if not doc.get("sys_file_size_mb") and payload.get("src_file_size"):
        try:
            file_size_bytes = float(payload.get("src_file_size"))
            if file_size_bytes > 0:
                doc["sys_file_size_mb"] = round(file_size_bytes / (1024 * 1024), 2)
        except (TypeError, ValueError):
            pass


def _apply_qdrant_payload(doc: Dict[str, Any], payload: Dict[str, Any]) -> None:
    _apply_field_map(doc, payload)
    _apply_toc(doc, payload)
    _apply_file_size(doc, payload)


def merge_qdrant_doc_links(documents: List[Dict[str, Any]], db: Any) -> None:
    if not documents or not db:
        return
    if not hasattr(db, "client") or not hasattr(db, "documents_collection"):
        return
    ids_needing_qdrant = _collect_qdrant_ids(documents)
    if not ids_needing_qdrant:
        return
    payload_by_id = _fetch_qdrant_payloads(db, ids_needing_qdrant)
    if not payload_by_id:
        return
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id") or doc.get("doc_id")
        if doc_id is None:
            continue
        payload = payload_by_id.get(str(doc_id))
        if payload:
            _apply_qdrant_payload(doc, payload)
