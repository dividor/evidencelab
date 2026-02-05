"""
Pytest configuration for integration tests
"""

import os
import sys
from pathlib import Path

import pytest

# Configure search parameters for consistent test results
os.environ["SEARCH_DENSE_WEIGHT"] = "0.5"

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def pytest_configure():
    api_base_url = os.getenv("API_BASE_URL")
    ui_base_url = os.getenv("UI_BASE_URL")
    if api_base_url != "http://api:8000" or ui_base_url != "http://ui:3000":
        pytest.exit(
            "Integration tests must run in Docker with "
            "API_BASE_URL=http://api:8000 and UI_BASE_URL=http://ui:3000",
            returncode=1,
        )
