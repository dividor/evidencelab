"""Guard against ui/backend/requirements.txt downgrading the root requirements.

The Docker image installs the root requirements first and the backend file
second, so a package pinned in both files must carry the same version or pip
silently replaces the root version with the backend one.
"""

import re
from pathlib import Path
from typing import Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_REQUIREMENTS = REPO_ROOT / "requirements.txt"
BACKEND_REQUIREMENTS = REPO_ROOT / "ui" / "backend" / "requirements.txt"

_PIN_PATTERN = re.compile(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;#]+)")


def parse_exact_pins(path: Path) -> Dict[str, str]:
    """Return {package_name: version} for every ``name==version`` line in a requirements file."""
    pins: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        match = _PIN_PATTERN.match(line)
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


@pytest.mark.unit
class TestBackendRequirementsMatchRoot:
    def test_parse_exact_pins_when_extras_and_comments_then_only_exact_pins_kept(
        self, tmp_path
    ):
        sample = tmp_path / "req.txt"
        sample.write_text(
            "fastapi==1.2.3  # comment\nuvicorn[standard]==0.4.0\npydantic>=2.0\n# only a comment\n"
        )
        assert parse_exact_pins(sample) == {"fastapi": "1.2.3", "uvicorn": "0.4.0"}

    def test_backend_pins_when_also_pinned_in_root_then_versions_match(self):
        root = parse_exact_pins(ROOT_REQUIREMENTS)
        backend = parse_exact_pins(BACKEND_REQUIREMENTS)
        shared = {name: (backend[name], root[name]) for name in backend if name in root}
        assert shared, "expected at least one package pinned in both files"
        mismatched = {
            name: f"backend={b} root={r}" for name, (b, r) in shared.items() if b != r
        }
        assert not mismatched, (
            "ui/backend/requirements.txt is installed after requirements.txt in the "
            f"Docker image and would downgrade these packages: {mismatched}"
        )
