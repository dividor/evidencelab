"""Unit tests for the customization config overlay merge (scripts/custom/merge_config.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "custom" / "merge_config.py"
)
_spec = importlib.util.spec_from_file_location("merge_config", _MODULE_PATH)
assert _spec and _spec.loader
merge_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge_config)


pytestmark = pytest.mark.unit


class TestDeepMerge:
    def test_nested_dicts_when_merged_then_recursively_combined(self):
        base = {"a": {"x": 1, "y": 2}}
        overlay = {"a": {"y": 3, "z": 4}}
        assert merge_config.deep_merge(base, overlay) == {"a": {"x": 1, "y": 3, "z": 4}}

    def test_scalar_when_overlaid_then_replaced(self):
        assert merge_config.deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_list_when_overlaid_then_replaced_not_concatenated(self):
        assert merge_config.deep_merge({"q": [1, 2, 3]}, {"q": [9]}) == {"q": [9]}

    def test_new_key_when_overlaid_then_added(self):
        assert merge_config.deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_null_value_when_overlaid_then_key_deleted(self):
        assert merge_config.deep_merge({"a": 1, "b": 2}, {"b": None}) == {"a": 1}

    def test_null_value_when_key_absent_then_noop(self):
        assert merge_config.deep_merge({"a": 1}, {"missing": None}) == {"a": 1}

    def test_replace_directive_when_set_then_subtree_replaced(self):
        base = {"ds": {"keep": 1, "old": 2}}
        overlay = {"ds": {"$replace": True, "only": 3}}
        assert merge_config.deep_merge(base, overlay) == {"ds": {"only": 3}}

    def test_base_not_mutated(self):
        base = {"a": {"x": 1}}
        merge_config.deep_merge(base, {"a": {"y": 2}})
        assert base == {"a": {"x": 1}}


class TestValidateOverlay:
    def test_unknown_top_level_key_when_present_then_raises(self):
        with pytest.raises(ValueError, match="Unknown top-level key"):
            merge_config.validate_overlay({"application": {}}, {"applicaton": {}})

    def test_known_keys_when_present_then_ok(self):
        merge_config.validate_overlay(
            {"application": {}, "datasources": {}}, {"datasources": {}}
        )

    def test_replace_directive_not_flagged_as_unknown(self):
        merge_config.validate_overlay({"datasources": {}}, {"$replace": True})


class TestRender:
    def _write(self, path: Path, data) -> Path:
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_empty_overlay_when_rendered_then_equals_base(self, tmp_path):
        base = self._write(tmp_path / "base.json", {"application": {"a": 1}})
        overlay = self._write(tmp_path / "overlay.json", {})
        assert merge_config.render(base, overlay) == {"application": {"a": 1}}

    def test_missing_overlay_file_when_rendered_then_equals_base(self, tmp_path):
        base = self._write(tmp_path / "base.json", {"application": {"a": 1}})
        missing = tmp_path / "does_not_exist.json"
        assert merge_config.render(base, missing) == {"application": {"a": 1}}

    def test_datasource_replace_when_rendered_then_only_overlay_kept(self, tmp_path):
        base = self._write(
            tmp_path / "base.json",
            {"datasources": {"A": {"k": 1}, "B": {"k": 2}}},
        )
        overlay = self._write(
            tmp_path / "overlay.json",
            {"datasources": {"$replace": True, "WFP": {"k": 9}}},
        )
        assert merge_config.render(base, overlay) == {"datasources": {"WFP": {"k": 9}}}

    def test_non_object_base_when_rendered_then_raises(self, tmp_path):
        base = self._write(tmp_path / "base.json", [1, 2, 3])
        overlay = self._write(tmp_path / "overlay.json", {})
        with pytest.raises(ValueError, match="must be a JSON object"):
            merge_config.render(base, overlay)
