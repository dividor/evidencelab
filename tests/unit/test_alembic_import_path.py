"""Migrations must be able to import application code without PYTHONPATH.

``0036_convert_brief_citations`` imports ``ui.backend.services``. The
containers set ``PYTHONPATH=/app``, but Demo E2E and host scripts run
``alembic upgrade`` directly on the machine, where the repository root is not
on ``sys.path``; there the migration failed with "No module named 'ui'".
``prepend_sys_path`` in ``alembic.ini`` puts the repository root on the path
wherever alembic runs from.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# Load the config and script directory as `alembic upgrade` does, then import
# the module migration 0036 needs. Runs in a fresh interpreter so this test
# process's own sys.path cannot hide a missing entry.
_IMPORT_AS_ALEMBIC_DOES = """
import importlib
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory

config = Config(sys.argv[1])
config.set_main_option("script_location", sys.argv[2])
ScriptDirectory.from_config(config)
importlib.import_module("ui.backend.services.brief_citations_convert")
"""


@pytest.mark.unit
class TestAlembicImportPath:
    def test_prepend_sys_path_when_config_loaded_then_is_repo_root(self):
        paths = Config(str(ALEMBIC_INI)).get_prepend_sys_paths_list()
        assert [Path(p).resolve() for p in paths] == [REPO_ROOT]

    def test_migration_import_when_run_outside_repo_without_pythonpath_then_succeeds(
        self, tmp_path
    ):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        result = subprocess.run(
            [
                sys.executable,
                "-P",
                "-c",
                _IMPORT_AS_ALEMBIC_DOES,
                str(ALEMBIC_INI),
                str(REPO_ROOT / "alembic"),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
