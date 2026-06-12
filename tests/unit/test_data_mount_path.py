"""Regression tests for DATA_MOUNT_PATH resolution.

A present-but-empty ``DATA_MOUNT_PATH`` (shipped as ``DATA_MOUNT_PATH=`` in
``.env.example`` and loaded by ``run_pipeline_host.sh`` in host mode) used to
collapse the scan/parse path to an absolute ``/<source>/pdfs`` and silently find
no documents. ``resolve_data_mount_path`` must treat empty as unset.
"""

import pytest

from pipeline.processors.parsing.parser_constants import (
    DEFAULT_DATA_MOUNT_PATH,
    resolve_data_mount_path,
)


@pytest.mark.unit
def test_resolve_data_mount_path_empty_returns_default(monkeypatch):
    """An empty env var (host-mode .env) falls back to the default."""
    monkeypatch.setenv("DATA_MOUNT_PATH", "")
    assert resolve_data_mount_path() == DEFAULT_DATA_MOUNT_PATH


@pytest.mark.unit
def test_resolve_data_mount_path_unset_returns_default(monkeypatch):
    """An absent env var falls back to the default."""
    monkeypatch.delenv("DATA_MOUNT_PATH", raising=False)
    assert resolve_data_mount_path() == DEFAULT_DATA_MOUNT_PATH


@pytest.mark.unit
def test_resolve_data_mount_path_set_returns_value(monkeypatch):
    """A configured value is returned verbatim (e.g. Docker's /app/data)."""
    monkeypatch.setenv("DATA_MOUNT_PATH", "/app/data")
    assert resolve_data_mount_path() == "/app/data"
