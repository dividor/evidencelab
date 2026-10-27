"""Stop the pipeline before a full data disk fails every document in turn.

When the data disk fills, each document still fails *individually* with
``OSError: [Errno 28] No space left on device`` and is marked ``parse_failed``
as though the document itself were bad. A long run then churns through its
whole queue producing nothing but failures. Measured on a UNEG backfill: 30
documents failed this way before anyone noticed the disk was at 100%.

Two triggers stop the feed:

* **Proactive** -- free space at the data directory drops below
  ``PIPELINE_MIN_FREE_DISK_MB`` (checked before the workers start and after
  every completed document).
* **Reactive** -- a worker result carries an ENOSPC error from any stage,
  which is definitive regardless of what the free-space figure says.

``PIPELINE_MIN_FREE_DISK_MB`` defaults to 5120 (5 GB). Set it to ``0`` to turn
off the proactive floor; the reactive trigger stays on.
"""

import logging
import os
import shutil
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MIN_FREE_DISK_MB = 5120

# Substrings that identify an ENOSPC failure in a stored error message.
_ENOSPC_MARKERS = ("No space left on device", "[Errno 28]")


class DiskSpaceExhausted(RuntimeError):
    """The data disk is full (or below the configured floor); the run stopped."""


def min_free_disk_mb() -> int:
    """The free-space floor in MB, from the environment.

    Unset means the default. A value that is set but not a non-negative
    integer is a configuration error and is reported, not ignored.
    """
    raw = os.getenv("PIPELINE_MIN_FREE_DISK_MB")
    if raw is None or not raw.strip():
        return DEFAULT_MIN_FREE_DISK_MB
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"PIPELINE_MIN_FREE_DISK_MB must be an integer number of MB, got {raw!r}"
        ) from exc
    if value < 0:
        raise ValueError(f"PIPELINE_MIN_FREE_DISK_MB must be >= 0, got {value}")
    return value


def free_disk_mb(path: str) -> int:
    """Free space in MB on the filesystem holding ``path``."""
    return shutil.disk_usage(path).free // (1024 * 1024)


def ensure_disk_space(path: str, context: str) -> int:
    """Return free MB at ``path``, raising ``DiskSpaceExhausted`` below the floor."""
    floor = min_free_disk_mb()
    free = free_disk_mb(path)
    if free < floor:
        raise DiskSpaceExhausted(
            f"Data disk has {free} MB free at {path!r}, below the "
            f"PIPELINE_MIN_FREE_DISK_MB floor of {floor} MB ({context}). "
            "Stopping so documents are not failed one by one on a full disk. "
            "Free space, then reset interrupted documents with "
            "scripts/pipeline/reset_failed_statuses.py --include-stuck."
        )
    return free


def result_reports_disk_full(result: Any) -> bool:
    """True when a worker result carries an ENOSPC error at the top level or in any stage."""
    if not isinstance(result, dict):
        return False
    texts = [str(result.get("error", ""))]
    stages = result.get("stages")
    if isinstance(stages, dict):
        texts.extend(
            str(stage.get("error", ""))
            for stage in stages.values()
            if isinstance(stage, dict)
        )
    return any(marker in text for text in texts for marker in _ENOSPC_MARKERS)
