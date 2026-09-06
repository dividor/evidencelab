"""The eval harness builds summaries from the same number of results the UI does."""

import pytest

from ui.backend.services.test_runner import (
    _group_settings_to_config,
    _summary_max_results,
)

pytestmark = pytest.mark.unit


def test_group_settings_map_summary_cap_keys():
    cfg = _group_settings_to_config(
        {
            "summaryLimitResults": False,
            "summaryMaxResults": 35,
            "wideSearch": True,
            "summaryTemperature": 0.4,
        }
    )
    assert cfg["summary_limit_results"] is False
    assert cfg["temperature"] == 0.4
    assert cfg["max_results"] == 35
    assert cfg["wide_search"] is True


def test_summary_max_results_uses_configured_cap():
    assert _summary_max_results({"max_results": 12}, result_count=50) == 12


def test_summary_max_results_defaults_to_twenty():
    assert _summary_max_results({}, result_count=50) == 20


def test_summary_max_results_uses_every_result_when_cap_is_off():
    assert (
        _summary_max_results(
            {"summary_limit_results": False, "max_results": 12}, result_count=87
        )
        == 87
    )
