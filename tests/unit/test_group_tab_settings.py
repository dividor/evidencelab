"""Unit tests for per-group feature-tab merge logic (users route helpers)."""

from types import SimpleNamespace

import pytest

from ui.backend.routes.users import TAB_KEYS, _merge_group_settings, _merge_tabs

pytestmark = pytest.mark.unit


def _group(name, search_settings):
    """A minimal stand-in for a UserGroup row."""
    return SimpleNamespace(name=name, search_settings=search_settings)


# ---------------------------------------------------------------------------
# _merge_tabs
# ---------------------------------------------------------------------------
class TestMergeTabs:
    def test_returns_all_tab_keys(self):
        merged = _merge_tabs([])
        assert set(merged.keys()) == set(TAB_KEYS)
        # No configs => everything disabled, no labels.
        assert all(not merged[t]["enabled"] for t in TAB_KEYS)

    def test_enabled_if_any_group_enables(self):
        a = {"search": {"enabled": True}, "assistant": {"enabled": False}}
        b = {"search": {"enabled": False}, "assistant": {"enabled": True}}
        merged = _merge_tabs([a, b])
        assert merged["search"]["enabled"] is True
        assert merged["assistant"]["enabled"] is True
        assert merged["brief"]["enabled"] is False  # absent everywhere

    def test_label_comes_from_first_enabling_group(self):
        a = {"brief": {"enabled": False, "label": "Disabled-Brief"}}
        b = {"brief": {"enabled": True, "label": "Briefings"}}
        c = {"brief": {"enabled": True, "label": "Reports"}}
        merged = _merge_tabs([a, b, c])
        assert merged["brief"]["enabled"] is True
        # 'a' disables it (ignored); 'b' is the first enabling group.
        assert merged["brief"]["label"] == "Briefings"

    def test_label_none_when_enabled_without_label(self):
        merged = _merge_tabs([{"heatmap": {"enabled": True, "label": "  "}}])
        assert merged["heatmap"]["enabled"] is True
        assert merged["heatmap"]["label"] is None  # frontend uses its default


# ---------------------------------------------------------------------------
# _merge_group_settings
# ---------------------------------------------------------------------------
class TestMergeGroupSettings:
    def test_no_tabs_key_when_no_group_configures_tabs(self):
        groups = [_group("Default", {"rerank": True}), _group("B", None)]
        merged = _merge_group_settings(groups)
        assert "tabs" not in merged
        assert merged["rerank"] is True

    def test_tabs_present_and_unioned_when_configured(self):
        groups = [
            _group("Default", {"tabs": {"search": {"enabled": True}}}),
            _group(
                "Editors",
                {"tabs": {"assistant": {"enabled": True, "label": "Ask"}}},
            ),
        ]
        merged = _merge_group_settings(groups)
        assert merged["tabs"]["search"]["enabled"] is True
        assert merged["tabs"]["assistant"]["enabled"] is True
        assert merged["tabs"]["assistant"]["label"] == "Ask"

    def test_tabs_special_cased_not_first_non_null(self):
        # First group enables only search; second enables brief. A naive
        # first-non-null merge would keep only the first group's tabs dict.
        groups = [
            _group("A", {"tabs": {"search": {"enabled": True}}}),
            _group("B", {"tabs": {"brief": {"enabled": True}}}),
        ]
        merged = _merge_group_settings(groups)
        assert merged["tabs"]["search"]["enabled"] is True
        assert merged["tabs"]["brief"]["enabled"] is True

    def test_other_keys_keep_first_non_null(self):
        groups = [
            _group("A", {"denseWeight": 0.5, "tabs": {"search": {"enabled": True}}}),
            _group("B", {"denseWeight": 0.9}),
        ]
        merged = _merge_group_settings(groups)
        assert merged["denseWeight"] == 0.5  # first wins
        assert merged["tabs"]["search"]["enabled"] is True
