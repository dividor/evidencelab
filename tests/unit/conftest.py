"""
Pytest configuration for test suite
"""

import sys
from pathlib import Path

# Add project root to path so tests can import project modules
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
