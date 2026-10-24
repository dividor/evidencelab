"""Compatibility shim for the notebook: the helpers now live in the app.

The citation check moved into the Evaluation Harness
(``ui/backend/services/citation_fidelity.py``); the notebook stays as a
transparent walkthrough of the same logic and imports it from there.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_module = importlib.import_module("ui.backend.services.citation_fidelity")
globals().update({k: v for k, v in vars(_module).items() if not k.startswith("_")})
