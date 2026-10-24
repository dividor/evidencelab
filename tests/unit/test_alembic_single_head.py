"""The migration graph must have exactly one head.

Two pull requests can each add a migration that revises the same parent; once
both merge, ``alembic upgrade head`` fails with "Multiple head revisions" and
the API container never starts. This test fails the build as soon as that
happens, so the merge revision is written before the branch is deployed.
"""

from pathlib import Path

import pytest

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]


def _script_directory() -> ScriptDirectory:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


@pytest.mark.unit
class TestAlembicSingleHead:
    def test_migration_graph_when_loaded_then_has_exactly_one_head(self):
        heads = _script_directory().get_heads()
        assert len(heads) == 1, f"alembic has {len(heads)} heads: {sorted(heads)}"

    def test_merge_revision_when_loaded_then_joins_both_1_6_4_heads(self):
        script = _script_directory()
        merge = script.get_revision("0037_merge_heads_1_6_4")
        assert set(merge.down_revision) == {
            "0036_add_test_run_config",
            "0036_convert_brief_citations",
        }
        assert script.get_heads() == ["0037_merge_heads_1_6_4"]
