from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pipeline.utilities.text_cleaning import clean_text


def _timeline_normalize_page_count(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count > 0 else None


def _timeline_extract_page_count(payload: Dict[str, Any]) -> Optional[int]:
    primary = _timeline_page_count_from_payload(
        payload,
        ("sys_page_count", "page_count", "sys_total_pages", "total_pages"),
    )
    if primary is not None:
        return primary
    stages = payload.get("sys_stages")
    stage_count = _timeline_page_count_from_stages(stages)
    if stage_count is not None:
        return stage_count
    toc_text = (
        payload.get("sys_toc") or payload.get("toc") or payload.get("toc_classified")
    )
    return _timeline_page_count_from_toc(toc_text)


def _timeline_page_count_from_payload(
    payload: Dict[str, Any], keys: tuple[str, ...]
) -> Optional[int]:
    for key in keys:
        value = _timeline_normalize_page_count(payload.get(key))
        if value is not None:
            return value
    return None


def _timeline_page_count_from_stages(stages: Any) -> Optional[int]:
    if not isinstance(stages, dict):
        return None
    parse_stage = stages.get("parse")
    if not isinstance(parse_stage, dict):
        return None
    return _timeline_normalize_page_count(parse_stage.get("page_count"))


def _timeline_page_count_from_toc(toc_text: Any) -> Optional[int]:
    if isinstance(toc_text, list):
        return _timeline_page_count_from_toc_list(toc_text)
    if isinstance(toc_text, str):
        return _timeline_page_count_from_toc_text(toc_text)
    return None


def _timeline_page_count_from_toc_list(toc_text: List[Any]) -> Optional[int]:
    pages: list[int] = []
    for entry in toc_text:
        if not isinstance(entry, dict):
            continue
        value = _timeline_normalize_page_count(
            entry.get("page") or entry.get("page_num")
        )
        if value is not None:
            pages.append(value)
    return max(pages) if pages else None


def _timeline_page_count_from_toc_text(toc_text: str) -> Optional[int]:
    matches = re.findall(r"\bpage\s+(\d+)\b", toc_text, flags=re.IGNORECASE)
    if not matches:
        return None
    max_page = _timeline_normalize_page_count(max(matches, key=int))
    return max_page


def _timeline_collect_docs_from_pg(pg) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for payload in pg.fetch_all_docs():
        if not isinstance(payload, dict):
            continue
        doc_id = payload.get("id") or payload.get("doc_id")
        if doc_id is None:
            continue
        sys_data = payload.get("sys_data")
        if not isinstance(sys_data, dict):
            sys_data = {}
        merged_payload = dict(sys_data)
        merged_payload.update(payload)
        stages = payload.get("sys_stages") or sys_data.get("sys_stages")
        if isinstance(stages, str):
            try:
                stages = json.loads(stages)
            except Exception:
                stages = None
        payload_page_count = _timeline_extract_page_count(merged_payload)
        status = payload.get("sys_status") or sys_data.get("sys_status")
        created_at = (
            payload.get("created_at")
            or sys_data.get("sys_created_at")
            or sys_data.get("created_at")
        )
        modified_at = (
            payload.get("modified_at")
            or sys_data.get("sys_modified_at")
            or sys_data.get("modified_at")
        )
        docs.append(
            {
                "id": str(doc_id),
                "title": payload.get("map_title"),
                "stages": stages,
                "status": status,
                "page_count": payload_page_count,
                "created_at": created_at,
                "modified_at": modified_at,
            }
        )
    return docs


def _timeline_collect_docs_from_qdrant(db) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    next_offset = None
    while True:
        results, next_offset = db.client.scroll(
            collection_name=db.documents_collection,
            limit=1000,
            offset=next_offset,
            with_payload=True,
        )
        if not results:
            break
        for point in results:
            payload = getattr(point, "payload", None) or {}
            if not isinstance(payload, dict):
                continue
            doc_id = payload.get("doc_id") or getattr(point, "id", None)
            if doc_id is None:
                continue
            payload_page_count = _timeline_extract_page_count(payload)
            docs.append(
                {
                    "id": str(doc_id),
                    "title": payload.get("map_title"),
                    "stages": payload.get("sys_stages"),
                    "status": payload.get("sys_status"),
                    "page_count": payload_page_count,
                    "created_at": payload.get("created_at"),
                    "modified_at": payload.get("modified_at"),
                }
            )
        if next_offset is None:
            break
    return docs


def _timeline_has_stage_data(docs: List[Dict[str, Any]]) -> bool:
    for doc in docs:
        stages = doc.get("stages")
        if isinstance(stages, dict) and stages:
            return True
    return False


def _timeline_stage_data(stages: Dict[str, Any], stage_key: str) -> Dict[str, Any]:
    stage_value = stages.get(stage_key)
    return stage_value if isinstance(stage_value, dict) else {}


def _timeline_resolve_phase_times(
    start_stage: Dict[str, Any], end_stage: Dict[str, Any]
) -> tuple[Optional[str], Optional[str]]:
    if not end_stage.get("at"):
        return None, None
    end_time_str = end_stage.get("at")
    start_time = None
    end_time = None
    if end_stage.get("elapsed_seconds"):
        try:
            elapsed_ms = float(end_stage.get("elapsed_seconds")) * 1000
            dt_end = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
            dt_start = dt_end - timedelta(milliseconds=elapsed_ms)
            start_time = dt_start.isoformat()
            end_time = end_time_str
        except Exception:
            pass
    if not start_time and start_stage.get("at"):
        s_time = start_stage.get("at")
        if s_time <= end_time_str:
            start_time = s_time
            end_time = end_time_str
    return start_time, end_time


def _timeline_page_count(doc: Dict[str, Any], stages: Dict[str, Any]) -> int:
    parse_stage = _timeline_stage_data(stages, "parse")
    page_count = _timeline_normalize_page_count(parse_stage.get("page_count"))
    if page_count is None:
        page_count = _timeline_normalize_page_count(doc.get("page_count")) or 0
    try:
        return int(page_count or 0)
    except (TypeError, ValueError):
        return 0


def _timeline_update_bounds(
    min_start: Optional[str],
    max_end: Optional[str],
    start_time: str,
    end_time: str,
) -> tuple[Optional[str], Optional[str]]:
    if min_start is None or start_time < min_start:
        min_start = start_time
    if max_end is None or end_time > max_end:
        max_end = end_time
    return min_start, max_end


def _timeline_append_phase_event(
    doc_phase_events: List[Dict[str, Any]],
    tooltip_lines: List[str],
    phase_name: str,
    doc_id: str,
    doc_title: str,
    start_time: str,
    end_time: str,
) -> None:
    doc_phase_events.append(
        {
            "start": start_time,
            "finish": end_time,
            "phase": phase_name,
            "doc_id": doc_id,
            "title": doc_title,
        }
    )
    s_short = start_time[11:19]
    e_short = end_time[11:19]
    tooltip_lines.append(f"{phase_name}: {s_short} - {e_short}")


def _timeline_build_doc_events(
    doc: Dict[str, Any], stages: Dict[str, Any], phases: List[tuple[str, str, str]]
) -> Optional[Dict[str, Any]]:
    doc_id = str(doc.get("id", "unknown"))
    doc_title = clean_text(doc.get("title", doc_id))
    doc_phase_events: List[Dict[str, Any]] = []
    min_start: Optional[str] = None
    max_end: Optional[str] = None

    tooltip_lines = [
        f"<b>{doc_title}</b>",
        f"ID: {doc_id}",
        "<br>Phase Breakdown:",
    ]

    for phase_name, start_stage_key, end_stage_key in phases:
        start_stage = _timeline_stage_data(stages, start_stage_key)
        end_stage = _timeline_stage_data(stages, end_stage_key)

        start_time, end_time = _timeline_resolve_phase_times(start_stage, end_stage)

        if start_time and end_time:
            min_start, max_end = _timeline_update_bounds(
                min_start, max_end, start_time, end_time
            )
            _timeline_append_phase_event(
                doc_phase_events,
                tooltip_lines,
                phase_name,
                doc_id,
                doc_title,
                start_time,
                end_time,
            )

    page_count = _timeline_page_count(doc, stages)

    if doc_phase_events and min_start and max_end:
        return {
            "id": doc_id,
            "start": min_start,
            "end": max_end,
            "events": doc_phase_events,
            "tooltip": "<br>".join(tooltip_lines),
            "page_count": page_count,
        }
    return None


def _timeline_collect_processed_docs(
    docs: List[Dict[str, Any]], phases: List[tuple[str, str, str]]
) -> List[Dict[str, Any]]:
    processed_docs: List[Dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        stages = doc.get("stages")
        if not isinstance(stages, dict) or not stages:
            continue
        doc_event = _timeline_build_doc_events(doc, stages, phases)
        if doc_event:
            processed_docs.append(doc_event)
    processed_docs.sort(key=lambda x: x["start"])
    return processed_docs


def _timeline_bucket_key(timestamp: str) -> str:
    return timestamp[:13] + ":00:00"


def _timeline_resolve_error_timestamp(doc: Dict[str, Any]) -> Optional[str]:
    stages = doc.get("stages")
    if not isinstance(stages, dict):
        stages = {}
    for stage in ["index", "tag", "summarize", "parse", "download"]:
        stage_data = _timeline_stage_data(stages, stage)
        if stage_data.get("at"):
            return stage_data.get("at")
    return doc.get("modified_at") or doc.get("created_at") or datetime.now().isoformat()


def _timeline_init_error_bucket(
    errors_buckets: Dict[str, Dict[str, int]], bucket_key: str
) -> None:
    if bucket_key not in errors_buckets:
        errors_buckets[bucket_key] = {
            "Parse Failed": 0,
            "Summarization Failed": 0,
            "Indexing Failed": 0,
        }


def _timeline_build_error_buckets(
    docs: List[Dict[str, Any]]
) -> Dict[str, Dict[str, int]]:
    errors_buckets: Dict[str, Dict[str, int]] = {}
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        timestamp = _timeline_resolve_error_timestamp(doc)
        if not timestamp:
            continue
        bucket_key = _timeline_bucket_key(timestamp)
        _timeline_init_error_bucket(errors_buckets, bucket_key)
        status = doc.get("status", "")
        if status == "parse_failed":
            errors_buckets[bucket_key]["Parse Failed"] += 1
        elif status == "summarize_failed":
            errors_buckets[bucket_key]["Summarization Failed"] += 1
        elif status == "index_failed":
            errors_buckets[bucket_key]["Indexing Failed"] += 1
    return errors_buckets


def _timeline_build_histograms(
    processed_docs: List[Dict[str, Any]],
    errors_buckets: Dict[str, Dict[str, int]],
) -> Dict[str, Dict[str, Any]]:
    histogram_buckets, pages_buckets, phase_dist_buckets = (
        _timeline_collect_histogram_buckets(processed_docs)
    )
    histograms = _timeline_format_histograms(
        histogram_buckets, pages_buckets, phase_dist_buckets
    )
    histograms["errors_histogram"] = _timeline_format_errors(errors_buckets)
    return histograms


def _timeline_collect_histogram_buckets(
    processed_docs: List[Dict[str, Any]],
) -> tuple[Dict[str, int], Dict[str, int], Dict[str, Dict[str, float]]]:
    histogram_buckets: Dict[str, int] = {}
    pages_buckets: Dict[str, int] = {}
    phase_dist_buckets: Dict[str, Dict[str, float]] = {}

    for doc in processed_docs:
        indexing_event = next(
            (e for e in doc["events"] if e["phase"] == "Indexing"), None
        )
        if not indexing_event:
            continue
        bucket_key = _timeline_bucket_key(indexing_event["finish"])
        histogram_buckets[bucket_key] = histogram_buckets.get(bucket_key, 0) + 1
        total_pages = int(doc.get("page_count", 0))
        pages_buckets[bucket_key] = pages_buckets.get(bucket_key, 0) + total_pages
        _timeline_update_phase_distribution(
            phase_dist_buckets, bucket_key, doc["events"]
        )

    return histogram_buckets, pages_buckets, phase_dist_buckets


def _timeline_update_phase_distribution(
    phase_dist_buckets: Dict[str, Dict[str, float]],
    bucket_key: str,
    events: List[Dict[str, Any]],
) -> None:
    if bucket_key not in phase_dist_buckets:
        phase_dist_buckets[bucket_key] = {
            "Parsing": 0.0,
            "Summarizing": 0.0,
            "Tagging": 0.0,
            "Indexing": 0.0,
        }
    for event in events:
        if event["phase"] not in phase_dist_buckets[bucket_key]:
            continue
        try:
            start = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
            finish = datetime.fromisoformat(event["finish"].replace("Z", "+00:00"))
            duration_ms = (finish - start).total_seconds() * 1000
            phase_dist_buckets[bucket_key][event["phase"]] += duration_ms
        except Exception:
            pass


def _timeline_format_histograms(
    histogram_buckets: Dict[str, int],
    pages_buckets: Dict[str, int],
    phase_dist_buckets: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, Any]]:
    sorted_buckets = sorted(histogram_buckets.items())
    histogram = {
        "x": [k for k, _ in sorted_buckets],
        "y": [v for _, v in sorted_buckets],
    }

    sorted_pages = sorted(pages_buckets.items())
    pages_histogram = {
        "x": [k for k, _ in sorted_pages],
        "y": [v for _, v in sorted_pages],
    }

    dist_x = sorted(phase_dist_buckets.keys())
    dist_data: Dict[str, List[Any]] = {
        "x": dist_x,
        "Parsing": [],
        "Summarizing": [],
        "Tagging": [],
        "Indexing": [],
    }

    for hour in dist_x:
        totals = phase_dist_buckets[hour]
        total_duration = sum(totals.values())
        if total_duration > 0:
            dist_data["Parsing"].append(totals["Parsing"] / total_duration)
            dist_data["Summarizing"].append(totals["Summarizing"] / total_duration)
            dist_data["Tagging"].append(totals["Tagging"] / total_duration)
            dist_data["Indexing"].append(totals["Indexing"] / total_duration)
        else:
            dist_data["Parsing"].append(0)
            dist_data["Summarizing"].append(0)
            dist_data["Tagging"].append(0)
            dist_data["Indexing"].append(0)

    return {
        "histogram": histogram,
        "pages_histogram": pages_histogram,
        "phase_distribution": dist_data,
    }


def _timeline_format_errors(
    errors_buckets: Dict[str, Dict[str, int]]
) -> Dict[str, Any]:
    sorted_error_buckets = sorted(errors_buckets.items())
    return {
        "x": [k for k, _ in sorted_error_buckets],
        "Parse Failed": [v["Parse Failed"] for _, v in sorted_error_buckets],
        "Summarization Failed": [
            v["Summarization Failed"] for _, v in sorted_error_buckets
        ],
        "Indexing Failed": [v["Indexing Failed"] for _, v in sorted_error_buckets],
    }
