"""Stage tracking helpers for pipeline database entries."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, TypedDict


class StageInfo(TypedDict, total=False):
    """Information about a processing stage."""

    success: bool
    at: str  # ISO 8601 timestamp
    error: Optional[str]
    # Stage-specific metadata (optional)
    page_count: Optional[int]
    word_count: Optional[int]
    method: Optional[str]
    chunks_count: Optional[int]


class Stages(TypedDict, total=False):
    """All processing stages for a document."""

    download: Optional[StageInfo]
    parse: Optional[StageInfo]
    summarize: Optional[StageInfo]
    tag: Optional[StageInfo]
    index: Optional[StageInfo]


def make_stage(success: bool, error: Optional[str] = None, **metadata) -> StageInfo:
    """
    Create a stage info dict with timestamp.

    Args:
        success: Whether the stage succeeded
        error: Error message if failed
        **metadata: Additional stage-specific metadata (page_count, method, etc.)

    Returns:
        StageInfo dict with success, timestamp, and any metadata
    """
    stage: StageInfo = {
        "success": success,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        stage["error"] = error
    # Add any additional metadata
    for key, value in metadata.items():
        if value is not None:
            stage[key] = value  # type: ignore
    return stage


def update_stages(
    existing_stages: Optional[Dict[str, Any]],
    stage_name: str,
    stage_info: StageInfo,
) -> Stages:
    """
    Update a single stage in the stages dict.

    Args:
        existing_stages: Current stages dict (or None)
        stage_name: Name of stage to update (download, parse, summarize, tag, index)
        stage_info: New stage info

    Returns:
        Updated stages dict
    """
    stages: Stages = dict(existing_stages) if existing_stages else {}  # type: ignore
    stages[stage_name] = stage_info  # type: ignore
    return stages
