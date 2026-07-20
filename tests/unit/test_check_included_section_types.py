"""Unit tests for the section-inclusion evaluation script glue.

The validation logic itself is covered by tests/unit/test_section_inclusion.py;
here we test the script-only helpers (document selection, report-row building).
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

INTRO_FIELD = (
    "Introduction - before beginning of Annexes (start_page_number, end_page_number)"
)


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


class TestBuildReportRow:
    def _doc(self, toc, page_range):
        return {
            "id": "doc-1",
            "sys_status": "indexed",
            "sys_data": {"sys_toc_classified": toc},
            "src_doc_raw_metadata": {INTRO_FIELD: page_range},
            "map_title": "Test Doc",
        }

    def test_build_report_row_when_body_annex_then_fail_row(self):
        toc = "[H1] Intro | context | page 13\n[H1] Misfiled | annexes | page 40\n"
        row = mod.build_report_row(self._doc(toc, "(13, 67)"), "wfp")
        assert row["status"] == "fail"
        assert row["doc_id"] == "doc-1"
        assert row["title"] == "Test Doc"
        assert row["data_source"] == "wfp"
        assert row["range_start"] == 13
        assert row["excluded_section_types"] == "annexes"
        assert "[annexes] Misfiled (p.40)" in row["excluded_details"]

    def test_build_report_row_has_all_report_headers(self):
        row = mod.build_report_row(
            self._doc("[H1] F | findings | page 30", "(13, 67)"), "wfp"
        )
        assert set(row.keys()) == set(mod.REPORT_HEADERS)

    def test_build_report_row_when_no_range_then_skipped(self):
        row = mod.build_report_row(
            self._doc("[H1] F | findings | page 30", None), "wfp"
        )
        assert row["status"] == "skipped"
        assert "missing_metadata_range" in row["reasons"]
