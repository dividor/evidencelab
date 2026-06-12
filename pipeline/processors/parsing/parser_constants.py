"""Shared constants for parsing processors."""

import os

# Page separator pattern for markdown output
PAGE_SEPARATOR = "\n\n------- Page Break -------\n\n"
DATA_PATH_PREFIX = "data/"
DEFAULT_DATA_MOUNT_PATH = "./data"


def resolve_data_mount_path() -> str:
    """Return the configured data mount path, defaulting to ``./data``.

    ``os.getenv("DATA_MOUNT_PATH", DEFAULT_DATA_MOUNT_PATH)`` only falls back to
    the default when the variable is *absent*. A present-but-empty value — e.g.
    ``DATA_MOUNT_PATH=`` shipped in ``.env.example`` and loaded by
    ``run_pipeline_host.sh`` in host mode — makes ``getenv`` return ``""``,
    which collapses ``f"{base}/{src}/pdfs"`` to an absolute ``/src/pdfs`` and
    breaks scanning. Treating empty as unset keeps host and Docker runs
    consistent (Docker sets ``DATA_MOUNT_PATH=/app/data`` explicitly).
    """
    return os.getenv("DATA_MOUNT_PATH") or DEFAULT_DATA_MOUNT_PATH
