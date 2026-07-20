"""Unit tests for the section-inclusion evaluation script.

Covers the pure logic: page-range parsing, classified-TOC parsing, detecting
sections in the body range tagged with default-excluded section types, and the
per-document evaluation verdict.
"""

import importlib.util
from pathlib import Path

import pytest

# The script lives under tests/evaluation/ and is not an importable package, so
# load it by path.
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "section_inclusion"
    / "check_included_section_types.py"
)
_spec = importlib.util.spec_from_file_location(
    "check_included_section_types", _SCRIPT_PATH
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


pytestmark = pytest.mark.unit


class TestParsePageRange:
    def test_parse_page_range_when_tuple_then_start_end(self):
        assert mod.parse_page_range((13, 67)) == (13, 67)

    def test_parse_page_range_when_list_then_start_end(self):
        assert mod.parse_page_range([13, 67]) == (13, 67)

    def test_parse_page_range_when_string_then_extracts_numbers(self):
        assert mod.parse_page_range("(13, 67)") == (13, 67)

    def test_parse_page_range_when_dict_then_named_keys(self):
        raw = {"start_page_number": 13, "end_page_number": 67}
        assert mod.parse_page_range(raw) == (13, 67)

    def test_parse_page_range_when_single_int_then_same_start_end(self):
        assert mod.parse_page_range(42) == (42, 42)

    def test_parse_page_range_when_none_then_none_pair(self):
        assert mod.parse_page_range(None) == (None, None)

    def test_parse_page_range_when_empty_string_then_none_pair(self):
        assert mod.parse_page_range("n/a") == (None, None)

    def test_parse_page_range_when_bool_not_treated_as_int(self):
        # bool is a subclass of int; must not be coerced to a page number.
        assert mod.parse_page_range(True) == (None, None)


class TestParseTocClassified:
    def test_parse_toc_classified_when_empty_then_no_entries(self):
        assert mod.parse_toc_classified("") == []

    def test_parse_toc_classified_when_lines_then_label_and_page(self):
        toc = (
            "[H1] Introduction | introduction | page 13\n"
            "  [H2] Methods | methodology | page 20\n"
            "[H1] Annexes | annexes | page 68\n"
        )
        entries = mod.parse_toc_classified(toc)
        assert len(entries) == 3
        assert entries[0] == {
            "title": "Introduction",
            "label": "introduction",
            "page": 13,
        }
        assert entries[1]["label"] == "methodology"
        assert entries[2]["page"] == 68

    def test_parse_toc_classified_when_no_page_then_page_none(self):
        entries = mod.parse_toc_classified("[H1] Foreword | front_matter")
        assert entries == [{"title": "Foreword", "label": "front_matter", "page": None}]

    def test_parse_toc_classified_ignores_unparseable_lines(self):
        entries = mod.parse_toc_classified("garbage line without pipes")
        assert entries == []

    def test_parse_toc_classified_when_trailing_front_marker_then_parsed(self):
        # Real WFP rows end with a bracket marker such as [Front].
        entries = mod.parse_toc_classified(
            "[H1] Rapport de l'évaluation | front_matter | page 1 [Front]"
        )
        assert entries == [
            {"title": "Rapport de l'évaluation", "label": "front_matter", "page": 1}
        ]

    def test_parse_toc_classified_when_roman_alias_and_marker_then_parsed(self):
        entries = mod.parse_toc_classified(
            "[H2] Résumé Exécutif | executive_summary | page 6 (i) [Front]"
        )
        assert entries == [
            {"title": "Résumé Exécutif", "label": "executive_summary", "page": 6}
        ]


class TestFindExcludedSections:
    def _entries(self):
        return [
            {"title": "Front", "label": "front_matter", "page": 5},  # before range
            {"title": "Findings", "label": "findings", "page": 20},  # included
            {
                "title": "Hidden Annex",
                "label": "annexes",
                "page": 40,
            },  # excluded, in range
            {
                "title": "Intro",
                "label": "introduction",
                "page": 15,
            },  # excluded, in range
            {"title": "Real Annex", "label": "annexes", "page": 80},  # after range
        ]

    def test_find_excluded_sections_flags_excluded_labels_in_range(self):
        result = mod.find_excluded_sections(self._entries(), 13, 67)
        labels = sorted(sec["label"] for sec in result)
        assert labels == ["annexes", "introduction"]

    def test_find_excluded_sections_ignores_included_labels(self):
        result = mod.find_excluded_sections(self._entries(), 13, 67)
        assert all(sec["label"] != "findings" for sec in result)

    def test_find_excluded_sections_ignores_out_of_range_pages(self):
        result = mod.find_excluded_sections(self._entries(), 13, 67)
        pages = {sec["page"] for sec in result}
        assert 5 not in pages and 80 not in pages

    def test_find_excluded_sections_when_all_included_then_empty(self):
        entries = [{"title": "F", "label": "findings", "page": 30}]
        assert mod.find_excluded_sections(entries, 13, 67) == []

    def test_find_excluded_sections_inclusive_of_boundaries(self):
        entries = [
            {"title": "Start", "label": "acronyms", "page": 13},
            {"title": "End", "label": "acronyms", "page": 67},
        ]
        result = mod.find_excluded_sections(entries, 13, 67)
        assert len(result) == 2

    def test_find_excluded_sections_skips_entries_without_page(self):
        entries = [{"title": "X", "label": "annexes", "page": None}]
        assert mod.find_excluded_sections(entries, 13, 67) == []

    def test_find_excluded_sections_custom_included_set(self):
        entries = [{"title": "M", "label": "methodology", "page": 20}]
        # methodology excluded when it is not in the custom included set
        result = mod.find_excluded_sections(entries, 13, 67, included=["findings"])
        assert len(result) == 1


class TestEvaluateDocument:
    def _payload(self, toc, page_range):
        """Build a doc row shaped like PostgresClient.fetch_all_docs() returns."""
        return {
            "id": "doc-1",
            "sys_status": "indexed",
            "sys_data": {"sys_toc_classified": toc},
            "src_doc_raw_metadata": {mod.INTRO_RANGE_FIELD: page_range},
            "map_title": "Test Doc",
        }

    def test_evaluate_document_when_body_annex_then_fail(self):
        toc = "[H1] Intro | context | page 13\n" "[H1] Misfiled | annexes | page 40\n"
        result = mod.evaluate_document(self._payload(toc, (13, 67)))
        assert result["status"] == "fail"
        assert result["num_excluded"] == 1
        assert "annexes" in result["excluded_section_types"]
        assert result["sections_in_range"] == 2

    def test_evaluate_document_when_all_included_then_pass(self):
        toc = "[H1] Findings | findings | page 30\n"
        result = mod.evaluate_document(self._payload(toc, (13, 67)))
        assert result["status"] == "pass"
        assert result["num_excluded"] == 0

    def test_evaluate_document_when_no_range_then_skipped(self):
        result = mod.evaluate_document(
            self._payload("[H1] F | findings | page 30", None)
        )
        assert result["status"] == "skipped"
        assert "missing_metadata_range" in result["reasons"]

    def test_evaluate_document_when_no_toc_then_skipped(self):
        result = mod.evaluate_document(self._payload("", (13, 67)))
        assert result["status"] == "skipped"
        assert "missing_toc_classified" in result["reasons"]

    def test_evaluate_document_when_range_is_string_then_parsed(self):
        # Real stored shape is a string such as "(11, 62)".
        toc = "[H1] Misfiled | annexes | page 40\n"
        result = mod.evaluate_document(self._payload(toc, "(11, 62)"))
        assert result["range_start"] == 11
        assert result["range_end"] == 62
        assert result["status"] == "fail"

    def test_evaluate_document_uses_map_title(self):
        result = mod.evaluate_document(
            self._payload("[H1] F | findings | page 30", "(13, 67)")
        )
        assert result["title"] == "Test Doc"


class TestSelectDocuments:
    def _docs(self):
        return [
            {"id": "a", "sys_status": "indexed"},
            {"id": "b", "sys_status": "parse_failed"},
            {"id": "c", "sys_status": "indexed"},
        ]

    def test_select_documents_filters_by_status(self):
        selected = mod.select_documents(self._docs(), None, None)
        assert [d["id"] for d in selected] == ["a", "c"]

    def test_select_documents_applies_limit(self):
        selected = mod.select_documents(self._docs(), 1, None)
        assert [d["id"] for d in selected] == ["a"]

    def test_select_documents_by_file_id(self):
        selected = mod.select_documents(self._docs(), None, "c")
        assert [d["id"] for d in selected] == ["c"]

    def test_select_documents_when_file_id_missing_then_raises(self):
        with pytest.raises(ValueError, match="not found"):
            mod.select_documents(self._docs(), None, "zzz")
