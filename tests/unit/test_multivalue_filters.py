"""Unit tests for multi-valued filter handling in the search routes.

Covers three defects surfaced by Heatmapper:

* filters on "; "-joined payload fields (country, theme, …) missed every
  multi-valued document (facet 26, filter 8);
* a multi-select title filter arrives comma-joined although titles contain
  commas, so it must be resolved to exact titles rather than substring-matched;
* the resolved title doc_ids must AND with other document-level constraints.
"""

import pytest
from qdrant_client.http import models as qmodels

from ui.backend.routes.search import _filter_match

pytestmark = pytest.mark.unit


class TestFilterMatch:
    def test_plain_string_then_match_value(self):
        match = _filter_match("Activity")
        assert isinstance(match, qmodels.MatchValue)
        assert match.value == "Activity"

    def test_comma_joined_then_match_any(self):
        match = _filter_match("Activity, Thematic")
        assert isinstance(match, qmodels.MatchAny)
        assert match.any == ["Activity", "Thematic"]

    def test_list_then_match_any_of_strings(self):
        match = _filter_match(["2024", 2025])
        assert isinstance(match, qmodels.MatchAny)
        assert match.any == ["2024", "2025"]
