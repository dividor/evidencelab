"""Unit tests for pipeline.validation.section_inclusion (pure logic)."""

import pytest

from pipeline.validation import section_inclusion as si

pytestmark = pytest.mark.unit


class TestParsePageRange:
    def test_parse_page_range_when_tuple_then_start_end(self):
        assert si.parse_page_range((13, 67)) == (13, 67)

    def test_parse_page_range_when_list_then_start_end(self):
        assert si.parse_page_range([13, 67]) == (13, 67)

    def test_parse_page_range_when_string_then_extracts_numbers(self):
        assert si.parse_page_range("(13, 67)") == (13, 67)

    def test_parse_page_range_when_dict_then_named_keys(self):
        raw = {"start_page_number": 13, "end_page_number": 67}
        assert si.parse_page_range(raw) == (13, 67)

    def test_parse_page_range_when_single_int_then_same_start_end(self):
        assert si.parse_page_range(42) == (42, 42)

    def test_parse_page_range_when_none_then_none_pair(self):
        assert si.parse_page_range(None) == (None, None)

    def test_parse_page_range_when_empty_string_then_none_pair(self):
        assert si.parse_page_range("n/a") == (None, None)

    def test_parse_page_range_when_bool_not_treated_as_int(self):
        # bool is a subclass of int; must not be coerced to a page number.
        assert si.parse_page_range(True) == (None, None)


class TestParseTocClassified:
    def test_parse_toc_classified_when_empty_then_no_entries(self):
        assert si.parse_toc_classified("") == []

    def test_parse_toc_classified_when_lines_then_label_and_page(self):
        toc = (
            "[H1] Introduction | introduction | page 13\n"
            "  [H2] Methods | methodology | page 20\n"
            "[H1] Annexes | annexes | page 68\n"
        )
        entries = si.parse_toc_classified(toc)
        assert len(entries) == 3
        assert entries[0] == {
            "title": "Introduction",
            "label": "introduction",
            "page": 13,
        }
        assert entries[1]["label"] == "methodology"
        assert entries[2]["page"] == 68

    def test_parse_toc_classified_when_no_page_then_page_none(self):
        entries = si.parse_toc_classified("[H1] Foreword | front_matter")
        assert entries == [{"title": "Foreword", "label": "front_matter", "page": None}]

    def test_parse_toc_classified_ignores_unparseable_lines(self):
        assert si.parse_toc_classified("garbage line without pipes") == []

    def test_parse_toc_classified_when_trailing_front_marker_then_parsed(self):
        # Real WFP rows end with a bracket marker such as [Front].
        entries = si.parse_toc_classified(
            "[H1] Rapport de l'evaluation | front_matter | page 1 [Front]"
        )
        assert entries == [
            {"title": "Rapport de l'evaluation", "label": "front_matter", "page": 1}
        ]

    def test_parse_toc_classified_when_roman_alias_and_marker_then_parsed(self):
        entries = si.parse_toc_classified(
            "[H2] Resume Executif | executive_summary | page 6 (i) [Front]"
        )
        assert entries == [
            {"title": "Resume Executif", "label": "executive_summary", "page": 6}
        ]


class TestFindExcludedSections:
    def _entries(self):
        return [
            {"title": "Front", "label": "front_matter", "page": 5},  # before range
            {"title": "Findings", "label": "findings", "page": 20},  # included
            {"title": "Hidden Annex", "label": "annexes", "page": 40},  # in range
            {"title": "Intro", "label": "introduction", "page": 15},  # in range
            {"title": "Real Annex", "label": "annexes", "page": 80},  # after range
        ]

    def test_find_excluded_sections_flags_excluded_labels_in_range(self):
        result = si.find_excluded_sections(self._entries(), 13, 67)
        assert sorted(sec["label"] for sec in result) == ["annexes", "introduction"]

    def test_find_excluded_sections_ignores_included_labels(self):
        result = si.find_excluded_sections(self._entries(), 13, 67)
        assert all(sec["label"] != "findings" for sec in result)

    def test_find_excluded_sections_ignores_out_of_range_pages(self):
        result = si.find_excluded_sections(self._entries(), 13, 67)
        pages = {sec["page"] for sec in result}
        assert 5 not in pages and 80 not in pages

    def test_find_excluded_sections_when_all_included_then_empty(self):
        entries = [{"title": "F", "label": "findings", "page": 30}]
        assert si.find_excluded_sections(entries, 13, 67) == []

    def test_find_excluded_sections_inclusive_of_boundaries(self):
        entries = [
            {"title": "Start", "label": "acronyms", "page": 13},
            {"title": "End", "label": "acronyms", "page": 67},
        ]
        assert len(si.find_excluded_sections(entries, 13, 67)) == 2

    def test_find_excluded_sections_skips_entries_without_page(self):
        entries = [{"title": "X", "label": "annexes", "page": None}]
        assert si.find_excluded_sections(entries, 13, 67) == []

    def test_find_excluded_sections_custom_included_set(self):
        entries = [{"title": "M", "label": "methodology", "page": 20}]
        result = si.find_excluded_sections(entries, 13, 67, included=["findings"])
        assert len(result) == 1


class TestSectionsInRange:
    def test_sections_in_range_filters_by_page(self):
        entries = [
            {"title": "a", "label": "x", "page": 10},
            {"title": "b", "label": "y", "page": 20},
            {"title": "c", "label": "z", "page": None},
        ]
        result = si.sections_in_range(entries, 15, 25)
        assert [e["title"] for e in result] == ["b"]


class TestEvaluateDocument:
    def _doc(self, toc, page_range):
        """A doc row shaped like PostgresClient.fetch_docs() returns."""
        return {
            "id": "doc-1",
            "sys_status": "indexed",
            "sys_data": {"sys_toc_classified": toc},
            "src_doc_raw_metadata": {si.INTRO_RANGE_FIELD: page_range},
            "map_title": "Test Doc",
        }

    def test_evaluate_document_when_body_annex_then_fail(self):
        toc = "[H1] Intro | context | page 13\n[H1] Misfiled | annexes | page 40\n"
        result = si.evaluate_document(self._doc(toc, (13, 67)))
        assert result["status"] == "fail"
        assert result["num_excluded"] == 1
        assert result["excluded_section_types"] == ["annexes"]
        assert result["sections_in_range"] == 2
        assert result["excluded_sections"][0]["title"] == "Misfiled"

    def test_evaluate_document_when_all_included_then_pass(self):
        toc = "[H1] Findings | findings | page 30\n"
        result = si.evaluate_document(self._doc(toc, (13, 67)))
        assert result["status"] == "pass"
        assert result["num_excluded"] == 0

    def test_evaluate_document_when_no_range_then_skipped(self):
        result = si.evaluate_document(self._doc("[H1] F | findings | page 30", None))
        assert result["status"] == "skipped"
        assert "missing_metadata_range" in result["reasons"]

    def test_evaluate_document_when_no_toc_then_skipped(self):
        result = si.evaluate_document(self._doc("", (13, 67)))
        assert result["status"] == "skipped"
        assert "missing_toc_classified" in result["reasons"]

    def test_evaluate_document_when_range_is_string_then_parsed(self):
        toc = "[H1] Misfiled | annexes | page 40\n"
        result = si.evaluate_document(self._doc(toc, "(11, 62)"))
        assert result["range_start"] == 11
        assert result["range_end"] == 62
        assert result["status"] == "fail"

    def test_evaluate_document_reads_toc_from_top_level(self):
        doc = {
            "id": "doc-2",
            "sys_toc_classified": "[H1] A | annexes | page 40",
            "src_doc_raw_metadata": {si.INTRO_RANGE_FIELD: (13, 67)},
            "map_title": "Top Level",
        }
        result = si.evaluate_document(doc)
        assert result["status"] == "fail"


class TestAccessors:
    def test_get_document_title_prefers_map_title(self):
        assert si.get_document_title({"map_title": "T"}) == "T"

    def test_get_document_title_falls_back_to_raw(self):
        doc = {"src_doc_raw_metadata": {"Title evaluation": "Eval"}}
        assert si.get_document_title(doc) == "Eval"

    def test_get_document_title_when_missing_then_unknown(self):
        assert si.get_document_title({}) == "Unknown"

    def test_describe_excluded_sections_formats_each(self):
        sections = [{"title": "Ch 4", "label": "annexes", "page": 40}]
        assert si.describe_excluded_sections(sections) == "[annexes] Ch 4 (p.40)"
