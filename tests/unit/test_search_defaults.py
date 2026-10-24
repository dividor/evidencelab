"""The harness's system search defaults must match the search UI's.

``ui/backend/services/search_defaults.SYSTEM_SEARCH_DEFAULTS`` is the backend
twin of ``SYSTEM_DEFAULTS`` in ``ui/frontend/src/utils/searchUrl.ts``. This test
parses the TypeScript literal so the two cannot drift apart silently.
"""

import re
from pathlib import Path

import pytest

from ui.backend.services import search_defaults
from ui.backend.services.test_runner import _GROUP_SETTING_MAP

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SEARCH_URL_TS = REPO / "ui/frontend/src/utils/searchUrl.ts"
SUMMARY_SELECTION_TS = REPO / "ui/frontend/src/utils/summarySelection.ts"


def _frontend_literals():
    src = SEARCH_URL_TS.read_text()
    block = re.search(
        r"SYSTEM_DEFAULTS: Required<SearchSettings> = \{(.*?)\n\};", src, re.S
    )
    assert block, "SYSTEM_DEFAULTS literal not found in searchUrl.ts"
    entries = dict(re.findall(r"^\s*(\w+):\s*(.+?),\s*$", block.group(1), re.M))
    boost = re.search(
        r"DEFAULT_FIELD_BOOST_FIELDS: Record<string, number> = \{(.*?)\}", src
    )
    assert boost
    pairs = re.findall(r"(\w+):\s*([\d.]+)", boost.group(1))
    summary_limit = re.search(
        r"export const SUMMARY_RESULT_LIMIT = (\d+)", SUMMARY_SELECTION_TS.read_text()
    )
    assert summary_limit
    return entries, pairs, int(summary_limit.group(1))


def _js_number(raw: str) -> str:
    value = float(raw)
    return str(int(value)) if value == int(value) else str(value)


def _ts_value(raw: str, pairs, summary_limit):
    if raw in ("true", "false"):
        return raw == "true"
    if raw == "SUMMARY_RESULT_LIMIT":
        return summary_limit
    if raw == "{ ...DEFAULT_FIELD_BOOST_FIELDS }":
        # Same "field:weight,..." encoding the UI puts on the /search request.
        return ",".join(f"{name}:{_js_number(weight)}" for name, weight in pairs)
    return float(raw)


# fieldBoostFields is serialised by the harness rather than mapped 1:1, so it is
# not in _GROUP_SETTING_MAP; compare it explicitly.
_EXTRA_KEYS = {"fieldBoostFields": "field_boost_fields"}


def test_system_search_defaults_match_frontend_system_defaults():
    entries, pairs, summary_limit = _frontend_literals()
    for camel, snake in {**_GROUP_SETTING_MAP, **_EXTRA_KEYS}.items():
        assert camel in entries, f"frontend SYSTEM_DEFAULTS lacks {camel}"
        assert snake in search_defaults.SYSTEM_SEARCH_DEFAULTS, f"backend lacks {snake}"
        expected = _ts_value(entries[camel], pairs, summary_limit)
        actual = search_defaults.SYSTEM_SEARCH_DEFAULTS[snake]
        assert actual == expected, f"{snake}: backend {actual!r} != UI {expected!r}"


def test_system_search_defaults_has_no_keys_the_ui_lacks():
    entries, _, _ = _frontend_literals()
    frontend_snake = set(_GROUP_SETTING_MAP.values()) | set(_EXTRA_KEYS.values())
    extra = set(search_defaults.SYSTEM_SEARCH_DEFAULTS) - frontend_snake
    assert not extra, f"backend defaults without a UI counterpart: {sorted(extra)}"
    assert "sectionTypes" in entries  # covered by default_section_types()


def test_default_section_types_is_the_config_driven_list(monkeypatch):
    monkeypatch.setattr(
        search_defaults,
        "get_default_included_section_types",
        lambda: ["findings", "recommendations"],
    )
    assert search_defaults.default_section_types() == "findings,recommendations"
