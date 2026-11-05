import pytest

"""
Pytest configuration for test suite
"""

import sys
from pathlib import Path

# Add project root to path so tests can import project modules
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


@pytest.fixture
def one_data_source(monkeypatch):
    """A deployment with one data source, so a request may name none."""
    from pipeline.db import config as db_config

    monkeypatch.setattr(db_config, "_configured_data_sources", lambda: ["uneg"])
