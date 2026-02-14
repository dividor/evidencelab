from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from qdrant_client.http import models as qmodels

from ui.backend.routes.stats_timeline import (
    _timeline_build_error_buckets,
    _timeline_build_histograms,
    _timeline_collect_docs_from_pg,
    _timeline_collect_docs_from_qdrant,
    _timeline_collect_processed_docs,
    _timeline_has_stage_data,
)
from ui.backend.utils.app_limits import get_rate_limits
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source, logger

RATE_LIMIT_SEARCH, RATE_LIMIT_DEFAULT, RATE_LIMIT_AI = get_rate_limits()
router = APIRouter()


def _sort_by_count(values: Dict[str, int]) -> Dict[str, int]:
    return dict(sorted(values.items(), key=lambda x: x[1], reverse=True))


def _sort_by_key_desc(values: Dict[str, int]) -> Dict[str, int]:
    return dict(sorted(values.items(), key=lambda x: str(x[0]), reverse=True))


def _sort_breakdown(
    breakdown: Dict[str, Dict[str, int]], sort_func
) -> Dict[str, Dict[str, int]]:
    totals = {k: sum(v.values()) for k, v in breakdown.items()}
    sorted_totals = sort_func(totals)
    return {k: breakdown[k] for k in sorted_totals}


def _indexed_counts(breakdown: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    return {k: v.get("indexed", 0) for k, v in breakdown.items()}


def _status_filter(status: str) -> qmodels.Filter:
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="sys_status", match=qmodels.MatchValue(value=status)
            )
        ]
    )


def _safe_facet_documents(db, key: str, filter_conditions=None, limit: int = 2000):
    try:
        try:
            return db.facet_documents(
                key,
                filter_conditions=filter_conditions,
                limit=limit,
                exact=False,
            )
        except TypeError:
            return db.facet_documents(
                key,
                filter_conditions=filter_conditions,
                limit=limit,
            )
    except Exception as exc:
        logger.warning("Facet failed for key=%s: %s", key, exc)
        return {}


def _build_breakdown_from_qdrant(
    db,
    field: str,
    statuses: List[str],
) -> Dict[str, Dict[str, int]]:
    breakdown: Dict[str, Dict[str, int]] = {}
    for status in statuses:
        facet_values = _safe_facet_documents(
            db, field, filter_conditions=_status_filter(status)
        )
        for value, count in facet_values.items():
            if value is None:
                continue
            breakdown.setdefault(value, {})[status] = count
    return breakdown


def _collect_stats_pg(pg) -> tuple[
    Dict[str, int],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
]:
    status_counts = pg.fetch_status_counts()
    agency_status_breakdown = _build_breakdown_from_pg(
        pg.fetch_field_status_breakdown("map_organization")
    )
    type_status_breakdown = _build_breakdown_from_pg(
        pg.fetch_field_status_breakdown("map_document_type")
    )
    year_status_breakdown = _build_breakdown_from_pg(
        pg.fetch_field_status_breakdown("map_published_year")
    )
    language_status_breakdown = _build_breakdown_from_pg(
        pg.fetch_field_status_breakdown("map_language"),
        skip_unknown=True,
        normalize_unknown=True,
    )
    if not language_status_breakdown:
        language_status_breakdown = _build_breakdown_from_pg(
            pg.fetch_field_status_breakdown("sys_language", from_sys_data=True),
            skip_unknown=True,
            normalize_unknown=True,
        )
    format_status_breakdown = _build_breakdown_from_pg(
        pg.fetch_field_status_breakdown("sys_file_format", from_sys_data=False),
        skip_empty=True,
    )
    return (
        status_counts,
        agency_status_breakdown,
        type_status_breakdown,
        year_status_breakdown,
        language_status_breakdown,
        format_status_breakdown,
    )


def _collect_stats_qdrant(db) -> tuple[
    Dict[str, int],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
]:
    status_counts = _safe_facet_documents(db, "sys_status")
    statuses = list(status_counts.keys())
    agency_status_breakdown = _build_breakdown_from_qdrant(
        db, "map_organization", statuses
    )
    type_status_breakdown = _build_breakdown_from_qdrant(
        db, "map_document_type", statuses
    )
    year_status_breakdown = _build_breakdown_from_qdrant(
        db, "map_published_year", statuses
    )
    language_status_breakdown = _build_breakdown_from_qdrant(
        db, "map_language", statuses
    )
    if not language_status_breakdown:
        language_status_breakdown = _build_breakdown_from_qdrant(
            db, "sys_language", statuses
        )
    format_status_breakdown = _build_breakdown_from_qdrant(
        db, "sys_file_format", statuses
    )
    return (
        status_counts,
        agency_status_breakdown,
        type_status_breakdown,
        year_status_breakdown,
        language_status_breakdown,
        format_status_breakdown,
    )


def _is_missing_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "does not exist" in message or "undefinedtable" in message


def _build_breakdown_from_pg(
    raw_breakdown: Dict[str, Dict[str, int]],
    *,
    skip_unknown: bool = False,
    normalize_unknown: bool = False,
    skip_empty: bool = False,
) -> Dict[str, Dict[str, int]]:
    breakdown: Dict[str, Dict[str, int]] = {}
    for raw_value, status_counts in raw_breakdown.items():
        value = _normalize_breakdown_key(
            raw_value,
            skip_unknown=skip_unknown,
            normalize_unknown=normalize_unknown,
            skip_empty=skip_empty,
        )
        if value is None:
            continue
        for status, count in status_counts.items():
            if count == 0:
                continue
            breakdown.setdefault(value, {})[status] = count
    return breakdown


def _normalize_breakdown_key(
    raw_value: Optional[str],
    *,
    skip_unknown: bool,
    normalize_unknown: bool,
    skip_empty: bool,
) -> Optional[str]:
    if raw_value is None:
        if not normalize_unknown:
            return None
        raw_value = "Unknown"
    if skip_unknown and raw_value == "Unknown":
        return None
    if skip_empty and not raw_value:
        return None
    if normalize_unknown and not raw_value:
        return "Unknown"
    return raw_value


def _init_org_flows():
    return defaultdict(  # type: ignore[var-annotated]
        lambda: {
            "total": 0,
            "downloaded": 0,
            "not_downloaded": 0,
            "parsed": 0,
            "parse_failed": 0,
            "stopped": 0,
            "parsing": 0,
            "summarized": 0,
            "summarize_failed": 0,
            "summarizing": 0,
            "indexed": 0,
            "index_failed": 0,
            "indexing": 0,
            "tagged": 0,
            "tagging": 0,
        }
    )


def _build_agency_breakdown(
    pg, field_name: str
) -> tuple[Dict[Any, int], Dict[str, Dict[str, int]]]:
    overall_counts = pg.fetch_field_counts(field_name)
    raw_breakdown = pg.fetch_field_status_breakdown(field_name)
    agency_breakdown: Dict[str, Dict[str, int]] = {
        agency: raw_breakdown.get(agency, {})
        for agency in overall_counts
        if agency != "Unknown"
    }
    return overall_counts, agency_breakdown


def _apply_status_counts(
    flows: Dict[str, int],
    status_counts: Dict[str, int],
    overall_counts: Dict[Any, int],
    agency: str,
) -> None:
    c_indexed = status_counts.get("indexed", 0)
    c_index_failed = status_counts.get("index_failed", 0)
    c_tagged = status_counts.get("tagged", 0)
    c_summarized = status_counts.get("summarized", 0)
    c_parsed = status_counts.get("parsed", 0)
    c_parse_failed = status_counts.get("parse_failed", 0)
    c_downloaded = status_counts.get("downloaded", 0)
    c_download_error = status_counts.get("download_error", 0)
    c_summarize_failed = status_counts.get("summarize_failed", 0)
    c_stopped = status_counts.get("stopped", 0)
    c_indexing = status_counts.get("indexing", 0)
    c_tagging = status_counts.get("tagging", 0)
    c_summarizing = status_counts.get("summarizing", 0)
    c_parsing = status_counts.get("parsing", 0)

    total_tagged = c_tagged + c_indexed + c_index_failed + c_indexing
    total_summarized = c_summarized + total_tagged + c_tagging
    total_parsed = c_parsed + total_summarized + c_summarizing + c_summarize_failed
    total_downloaded = (
        c_downloaded + total_parsed + c_parse_failed + c_parsing + c_stopped
    )

    flows["indexed"] += c_indexed
    flows["index_failed"] += c_index_failed
    flows["tagged"] += total_tagged
    flows["summarized"] += total_summarized
    flows["parsed"] += total_parsed
    flows["parse_failed"] += c_parse_failed
    flows["summarize_failed"] += c_summarize_failed
    flows["downloaded"] += total_downloaded

    flows["indexing"] += c_tagged + c_indexing
    flows["tagging"] += c_summarized + c_tagging
    flows["summarizing"] += c_parsed + c_summarizing
    flows["stopped"] += c_stopped
    flows["parsing"] += c_downloaded + c_parsing
    flows["not_downloaded"] = c_download_error

    flows["total"] = total_downloaded + flows["not_downloaded"]
    if flows["total"] == 0:
        flows["total"] = overall_counts.get(agency, 0)


def _calculate_org_flows(
    agency_breakdown: Dict[str, Dict[str, int]], overall_counts: Dict[Any, int]
) -> Dict[str, Dict[str, int]]:
    org_flows = _init_org_flows()
    for agency, status_counts in agency_breakdown.items():
        _apply_status_counts(org_flows[agency], status_counts, overall_counts, agency)
    return org_flows


def _build_sankey_nodes(org_flows: Dict[str, Dict[str, int]]):
    nodes: List[str] = []
    node_idx: Dict[str, int] = {}
    node_colors: List[str] = []

    org_colors = [
        "rgb(102, 194, 165)",
        "rgb(252, 141, 98)",
        "rgb(141, 160, 203)",
        "rgb(231, 138, 195)",
        "rgb(166, 216, 84)",
        "rgb(255, 217, 47)",
        "rgb(229, 196, 148)",
        "rgb(179, 179, 179)",
    ]

    org_color_map: Dict[str, str] = {}
    sorted_orgs = sorted(org_flows.keys())

    for idx, org in enumerate(sorted_orgs):
        org_color_map[org] = org_colors[idx % len(org_colors)]
        node_idx[f"{org}_total"] = len(nodes)
        nodes.append(f"{org} ({org_flows[org]['total']})")
        node_colors.append(org_color_map[org])

    totals = {
        "downloaded": sum(f["downloaded"] for f in org_flows.values()),
        "not_downloaded": sum(f["not_downloaded"] for f in org_flows.values()),
        "parsed": sum(f["parsed"] for f in org_flows.values()),
        "parse_failed": sum(f["parse_failed"] for f in org_flows.values()),
        "stopped": sum(f["stopped"] for f in org_flows.values()),
        "parsing": sum(f["parsing"] for f in org_flows.values()),
        "summarized": sum(f["summarized"] for f in org_flows.values()),
        "summarize_failed": sum(f["summarize_failed"] for f in org_flows.values()),
        "summarizing": sum(f["summarizing"] for f in org_flows.values()),
        "tagged": sum(f["tagged"] for f in org_flows.values()),
        "tagging": sum(f["tagging"] for f in org_flows.values()),
        "indexed": sum(f["indexed"] for f in org_flows.values()),
        "index_failed": sum(f["index_failed"] for f in org_flows.values()),
        "indexing": sum(f["indexing"] for f in org_flows.values()),
    }

    def add_node(key: str, label: str, color: str) -> None:
        node_idx[key] = len(nodes)
        nodes.append(label)
        node_colors.append(color)

    add_node("downloaded", f"Downloaded ({totals['downloaded']})", "rgb(100, 116, 139)")
    add_node(
        "not_downloaded",
        f"Document unavailable ({totals['not_downloaded']})",
        "rgb(253, 224, 71)",
    )
    add_node("parsed", f"Parsed ({totals['parsed']})", "rgb(139, 92, 246)")
    add_node(
        "parse_failed",
        f"Parse Failed ({totals['parse_failed']})",
        "rgb(239, 68, 68)",
    )
    add_node(
        "stopped",
        f"Stopped ({totals['stopped']})",
        "rgb(239, 68, 68)",
    )
    add_node(
        "parsing",
        f"Parsing ({totals['parsing']})",
        "rgb(200, 200, 200)",
    )
    add_node("summarized", f"Summarized ({totals['summarized']})", "rgb(16, 185, 129)")
    add_node(
        "summarize_failed",
        f"Summarize Failed ({totals['summarize_failed']})",
        "rgb(239, 68, 68)",
    )
    add_node(
        "summarizing",
        f"Summarizing ({totals['summarizing']})",
        "rgb(200, 200, 200)",
    )
    add_node("tagged", f"Tagged ({totals['tagged']})", "rgb(245, 158, 11)")
    add_node(
        "tagging",
        f"Tagging ({totals['tagging']})",
        "rgb(200, 200, 200)",
    )
    add_node("indexed", f"Indexed ({totals['indexed']})", "rgb(14, 165, 233)")
    add_node(
        "index_failed",
        f"Index Failed ({totals['index_failed']})",
        "rgb(239, 68, 68)",
    )
    add_node(
        "indexing",
        f"Indexing ({totals['indexing']})",
        "rgb(200, 200, 200)",
    )

    return nodes, node_idx, node_colors, org_color_map, sorted_orgs


def _rgb_to_rgba(rgb: str, alpha: float = 0.3) -> str:
    """Convert 'rgb(r, g, b)' to 'rgba(r, g, b, alpha)' for transparent links."""
    return rgb.replace("rgb(", "rgba(").replace(")", f", {alpha})")


def _build_sankey_links(
    org_flows: Dict[str, Dict[str, int]],
    node_idx: Dict[str, int],
    org_color_map: Dict[str, str],
    sorted_orgs: List[str],
) -> Dict[str, List[Any]]:
    sources: List[int] = []
    targets: List[int] = []
    values: List[int] = []
    link_colors: List[str] = []

    def add_link(source_key: str, target_key: str, value: int, color: str) -> None:
        if value <= 0:
            return
        sources.append(node_idx[source_key])
        targets.append(node_idx[target_key])
        values.append(value)
        link_colors.append(color)

    link_alpha = 0.25

    for org in sorted_orgs:
        flows = org_flows[org]
        add_link(
            f"{org}_total",
            "downloaded",
            flows["downloaded"],
            _rgb_to_rgba(org_color_map[org], link_alpha),
        )
        add_link(
            f"{org}_total",
            "not_downloaded",
            flows["not_downloaded"],
            _rgb_to_rgba("rgb(253, 224, 71)", 0.4),
        )
        add_link(
            "downloaded",
            "parsed",
            flows["parsed"],
            _rgb_to_rgba("rgb(139, 92, 246)", link_alpha),
        )
        add_link(
            "downloaded",
            "parse_failed",
            flows["parse_failed"],
            _rgb_to_rgba("rgb(239, 68, 68)", 0.35),
        )
        add_link(
            "downloaded",
            "stopped",
            flows["stopped"],
            _rgb_to_rgba("rgb(239, 68, 68)", 0.35),
        )
        add_link(
            "downloaded",
            "parsing",
            flows["parsing"],
            _rgb_to_rgba("rgb(200, 200, 200)", link_alpha),
        )
        add_link(
            "parsed",
            "summarized",
            flows["summarized"],
            _rgb_to_rgba("rgb(16, 185, 129)", link_alpha),
        )
        add_link(
            "parsed",
            "summarize_failed",
            flows["summarize_failed"],
            _rgb_to_rgba("rgb(239, 68, 68)", 0.35),
        )
        add_link(
            "parsed",
            "summarizing",
            flows["summarizing"],
            _rgb_to_rgba("rgb(200, 200, 200)", link_alpha),
        )
        add_link(
            "summarized",
            "tagged",
            flows["tagged"],
            _rgb_to_rgba("rgb(245, 158, 11)", link_alpha),
        )
        add_link(
            "summarized",
            "tagging",
            flows["tagging"],
            _rgb_to_rgba("rgb(200, 200, 200)", link_alpha),
        )
        add_link(
            "tagged",
            "indexed",
            flows["indexed"],
            _rgb_to_rgba("rgb(14, 165, 233)", link_alpha),
        )
        add_link(
            "tagged",
            "index_failed",
            flows["index_failed"],
            _rgb_to_rgba("rgb(239, 68, 68)", 0.35),
        )
        add_link(
            "tagged",
            "indexing",
            flows["indexing"],
            _rgb_to_rgba("rgb(200, 200, 200)", link_alpha),
        )

    return {"source": sources, "target": targets, "value": values, "color": link_colors}


def _build_sankey_annotations(
    org_flows: Dict[str, Dict[str, int]], sorted_orgs: List[str]
) -> Dict[str, int]:
    totals = {
        "downloaded": sum(f["downloaded"] for f in org_flows.values()),
        "not_downloaded": sum(f["not_downloaded"] for f in org_flows.values()),
        "parsed": sum(f["parsed"] for f in org_flows.values()),
        "summarized": sum(f["summarized"] for f in org_flows.values()),
        "tagged": sum(f["tagged"] for f in org_flows.values()),
        "indexed": sum(f["indexed"] for f in org_flows.values()),
    }
    total_records = sum(org_flows[org]["total"] for org in sorted_orgs)
    return {
        "num_orgs": len(sorted_orgs),
        "total_records": total_records,
        "layer2_count": totals["downloaded"] + totals["not_downloaded"],
        "layer3_count": totals["parsed"],
        "layer4_count": totals["summarized"],
        "layer5_count": totals["tagged"],
        "layer6_count": totals["indexed"],
    }


@router.get("/stats")
def get_stats(
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """
    Get pipeline statistics for dashboard.
    Returns counts and breakdowns by organization, type, status.
    Uses Postgres sidecar fields for counting.
    """
    try:
        pg = get_pg_for_source(data_source)
        (
            status_counts,
            agency_status_breakdown,
            type_status_breakdown,
            year_status_breakdown,
            language_status_breakdown,
            format_status_breakdown,
        ) = _collect_stats_pg(pg)

        total_docs = sum(status_counts.values())
        indexed_docs = status_counts.get("indexed", 0)

        return {
            "total_documents": total_docs,
            "indexed_documents": indexed_docs,
            "total_agencies": len(agency_status_breakdown),
            "status_breakdown": _sort_by_count(status_counts),
            "agency_breakdown": _sort_breakdown(
                agency_status_breakdown, _sort_by_count
            ),
            "type_breakdown": _sort_breakdown(type_status_breakdown, _sort_by_count),
            "year_breakdown": _sort_breakdown(year_status_breakdown, _sort_by_key_desc),
            "language_breakdown": _sort_breakdown(
                language_status_breakdown, _sort_by_count
            ),
            "agency_indexed": _indexed_counts(agency_status_breakdown),
            "type_indexed": _indexed_counts(type_status_breakdown),
            "year_indexed": _indexed_counts(year_status_breakdown),
            "language_indexed": _indexed_counts(language_status_breakdown),
            "format_breakdown": _sort_breakdown(
                format_status_breakdown, _sort_by_count
            ),
            "format_indexed": _indexed_counts(format_status_breakdown),
        }

    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/sankey")
def get_sankey_data(
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """
    Get Sankey diagram data for pipeline flow visualization.
    Based on the logic from scripts/stats.py
    """
    try:
        pg = get_pg_for_source(data_source)
        overall_counts, agency_breakdown = _build_agency_breakdown(
            pg, field_name="map_organization"
        )
        org_flows = _calculate_org_flows(agency_breakdown, overall_counts)
        nodes, node_idx, node_colors, org_color_map, sorted_orgs = _build_sankey_nodes(
            org_flows
        )
        links = _build_sankey_links(org_flows, node_idx, org_color_map, sorted_orgs)
        annotations = _build_sankey_annotations(org_flows, sorted_orgs)

        return {
            "nodes": nodes,
            "links": links,
            "node_colors": node_colors,
            "annotations": annotations,
        }
    except Exception as e:
        logger.error(f"Sankey error: {e}")
        if _is_missing_table_error(e):
            empty_links: Dict[str, List[Any]] = {
                "source": [],
                "target": [],
                "value": [],
                "color": [],
            }
            return {
                "nodes": [],
                "links": empty_links,
                "node_colors": [],
                "annotations": {
                    "num_orgs": 0,
                    "total_records": 0,
                    "layer2_count": 0,
                    "layer3_count": 0,
                    "layer4_count": 0,
                },
            }
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/timeline")
def get_timeline_data(
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """
    Get timeline data for pipeline processing visualization.
    Returns events for parsing, summarizing, tagging, and indexing phases.
    """
    try:
        pg = get_pg_for_source(data_source)
        docs = _timeline_collect_docs_from_pg(pg)
        if not _timeline_has_stage_data(docs):
            db = get_db_for_source(data_source)
            docs = _timeline_collect_docs_from_qdrant(db)
        phases = [
            ("Parsing", "download", "parse"),
            ("Summarizing", "parse", "summarize"),
            ("Tagging", "summarize", "tag"),
            ("Indexing", "tag", "index"),
        ]
        processed_docs = _timeline_collect_processed_docs(docs, phases)
        errors_buckets = _timeline_build_error_buckets(docs)
        return _timeline_build_histograms(processed_docs, errors_buckets)
    except Exception as e:
        logger.exception("Timeline error")
        if _is_missing_table_error(e):
            return _timeline_build_histograms([], {})
        raise HTTPException(status_code=500, detail=str(e))
