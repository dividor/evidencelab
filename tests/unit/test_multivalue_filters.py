"""Unit tests for multi-valued filter handling in the search routes.

Covers three defects surfaced by Heatmapper:

* filters on "; "-joined payload fields (country, theme, …) missed every
  multi-valued document (facet 26, filter 8);
* a multi-select title filter arrives comma-joined although titles contain
  commas, so it must be resolved to exact titles rather than substring-matched;
* the resolved title doc_ids must AND with other document-level constraints.
"""

from unittest.mock import MagicMock, patch

import pytest
from qdrant_client.http import models as qmodels

from ui.backend.routes.search import (
    _NO_MATCH_DOC_ID,
    _filter_match,
    _handle_title_filter,
    _resolve_title_doc_ids,
    _title_candidates,
)
from ui.backend.utils.filter_helpers import (
    _is_expandable_filter,
    expand_multivalue_filters,
)

pytestmark = pytest.mark.unit


def _db_with_values(values):
    db = MagicMock()
    db.facet_documents.return_value = {v: 1 for v in values}
    return db


class TestExpandMultivalueFilters:
    def test_single_value_when_joined_payloads_exist_then_expanded_to_list(self):
        db = _db_with_values(["Kenya", "Kenya; Ethiopia", "Malawi"])
        core = {"country": "Kenya"}
        expand_multivalue_filters(db, core, "wfp")
        assert core["country"] == ["Kenya", "Kenya; Ethiopia"]
        db.facet_documents.assert_called_once()
        assert db.facet_documents.call_args.kwargs["key"] == "map_country"

    def test_multi_select_when_joined_payloads_exist_then_all_kept(self):
        db = _db_with_values(["Kenya", "Kenya; Ethiopia", "Malawi", "Niger; Malawi"])
        core = {"country": "Kenya,Malawi"}
        expand_multivalue_filters(db, core, "wfp")
        assert core["country"] == [
            "Kenya",
            "Kenya; Ethiopia",
            "Malawi",
            "Niger; Malawi",
        ]

    def test_value_when_nothing_to_add_then_left_as_string(self):
        db = _db_with_values(["Activity", "Thematic"])
        core = {"document_type": "Activity"}
        expand_multivalue_filters(db, core, "wfp")
        assert core["document_type"] == "Activity"

    def test_skipped_fields_when_present_then_never_looked_up(self):
        db = MagicMock()
        core = {
            "title": "A title",
            "doc_id": "1,2",
            "language": "en",
            "region": "Asia",
            "published_year": "2024",
            "src_evaluation_category": "CE",
            "tag_sdg": "sdg1 - SDG1",
            "score_min": "3",
            "country": None,
            "theme": "",
        }
        before = dict(core)
        expand_multivalue_filters(db, core, "wfp")
        assert core == before
        db.facet_documents.assert_not_called()

    def test_list_value_when_already_expanded_then_left_untouched(self):
        db = MagicMock()
        core = {"country": ["Kenya", "Kenya; Ethiopia"]}
        expand_multivalue_filters(db, core, "wfp")
        assert core["country"] == ["Kenya", "Kenya; Ethiopia"]
        db.facet_documents.assert_not_called()


class TestIsExpandableFilter:
    @pytest.mark.parametrize(
        "field, value, expected",
        [
            ("country", "Kenya", True),
            ("organization", "WFP", True),
            ("theme", "Nutrition", True),
            ("title", "x", False),
            ("region", "x", False),
            ("published_year", "2024", False),
            ("src_quality_rating", "x", False),
            ("tag_sdg", "x", False),
            ("num_citations_max", "5", False),
            ("country", "", False),
            ("country", "   ", False),
            ("country", ["Kenya"], False),
            ("country", None, False),
        ],
    )
    def test_field_and_value_then_expected(self, field, value, expected):
        assert _is_expandable_filter(field, value) is expected


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


class TestTitleCandidates:
    def test_single_title_then_only_itself(self):
        assert _title_candidates("Evaluation of X") == ["Evaluation of X"]

    def test_two_titles_then_each_and_joined(self):
        candidates = _title_candidates("Title A,Title B")
        assert "Title A" in candidates
        assert "Title B" in candidates
        assert "Title A,Title B" in candidates

    def test_title_with_comma_then_reconstructed_with_space(self):
        candidates = _title_candidates("Partnerships in East Africa, 2016-2020")
        assert "Partnerships in East Africa, 2016-2020" in candidates

    def test_two_titles_one_with_comma_then_both_reconstructed(self):
        candidates = _title_candidates("Title A,Region Study, 2016-2020,Title C")
        assert "Title A" in candidates
        assert "Region Study, 2016-2020" in candidates
        assert "Title C" in candidates

    def test_blank_parts_then_dropped(self):
        assert _title_candidates(" , ,A, ") == [", ,A,", "A"]

    def test_many_parts_then_only_parts_and_whole(self):
        parts = [f"T{i}" for i in range(60)]
        candidates = _title_candidates(",".join(parts))
        assert set(parts) <= set(candidates)
        assert len(candidates) == len(parts) + 1


class TestResolveTitleDocIds:
    def test_exact_and_substring_matches_then_unioned_sorted(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_exact_titles.return_value = ["d3", "d1"]
        pg.fetch_doc_ids_by_title.return_value = ["d2", "d1"]
        assert _resolve_title_doc_ids(pg, "Title A,Title B") == ["d1", "d2", "d3"]
        pg.fetch_doc_ids_by_title.assert_called_once_with("Title A,Title B")


class TestHandleTitleFilter:
    def test_title_when_resolved_then_intersected_with_existing_doc_id(self):
        # Regression: the title doc_ids used to overwrite a language/region
        # constraint instead of ANDing with it.
        core = {"title": "Title A", "doc_id": "d1,d2"}
        with patch(
            "ui.backend.routes.search._resolve_title_doc_ids",
            return_value=["d2", "d9"],
        ):
            assert _handle_title_filter(MagicMock(), core, "q") is None
        assert "title" not in core
        assert core["doc_id"] == "d2"

    def test_title_when_disjoint_from_existing_then_sentinel(self):
        core = {"title": "Title A", "doc_id": "d1"}
        with patch(
            "ui.backend.routes.search._resolve_title_doc_ids", return_value=["d9"]
        ):
            _handle_title_filter(MagicMock(), core, "q")
        assert core["doc_id"] == _NO_MATCH_DOC_ID

    def test_title_when_no_match_then_empty_response(self):
        core = {"title": "Nope"}
        with patch("ui.backend.routes.search._resolve_title_doc_ids", return_value=[]):
            response = _handle_title_filter(MagicMock(), core, "q")
        assert response is not None
        assert response.total == 0
        assert response.filters == {"title": ["Nope"]}

    def test_no_title_then_untouched(self):
        core = {"country": "Kenya"}
        assert _handle_title_filter(MagicMock(), core, "q") is None
        assert core == {"country": "Kenya"}
