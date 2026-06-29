"""Unit tests for the chunk doc-field backfill helpers.

Locks in the pure logic that decides where each field's value is read from
(PG column vs src_doc_raw_metadata JSONB) and how documents are grouped by
value for batched Qdrant writes — without a DB or Qdrant.
"""

import importlib.util
from pathlib import Path

import pytest

# The script lives under scripts/fixes/ (not a package); import it by path.
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "fixes"
    / "backfill_chunk_doc_fields.py"
)
_spec = importlib.util.spec_from_file_location(
    "backfill_chunk_doc_fields", _SCRIPT_PATH
)
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)


BLOCK = {
    "data_subdir": "wfp",
    "src_field_mapping": {
        "src_evaluation_category": "Evaluation category",
        "src_quality_rating": "Quality rating",
    },
}


# ---------------------------------------------------------------------------
# resolve_source
# ---------------------------------------------------------------------------


class TestResolveSource:
    def test_resolves_by_key(self):
        config = {"datasources": {"wfp": {"data_subdir": "wfp"}}}
        subdir, block = bf.resolve_source(config, "wfp")
        assert subdir == "wfp"
        assert block == {"data_subdir": "wfp"}

    def test_resolves_by_subdir(self):
        config = {"datasources": {"wfp_key": {"data_subdir": "wfp_sub"}}}
        subdir, _block = bf.resolve_source(config, "wfp_sub")
        assert subdir == "wfp_sub"

    def test_unknown_source_raises(self):
        with pytest.raises(SystemExit):
            bf.resolve_source({"datasources": {}}, "nope")


# ---------------------------------------------------------------------------
# build_field_specs
# ---------------------------------------------------------------------------


class TestBuildFieldSpecs:
    def test_src_field_resolves_to_jsonb_raw_key(self):
        specs = bf.build_field_specs(BLOCK, ["src_evaluation_category"])
        assert specs == [
            bf.FieldSpec("src_evaluation_category", "jsonb", "Evaluation category")
        ]

    def test_map_field_resolves_to_column(self):
        specs = bf.build_field_specs(BLOCK, ["map_region"])
        assert specs == [bf.FieldSpec("map_region", "column", "map_region")]

    def test_src_field_without_mapping_is_skipped(self):
        specs = bf.build_field_specs(BLOCK, ["src_unmapped"])
        assert specs == []

    def test_illegal_field_name_raises(self):
        with pytest.raises(SystemExit):
            bf.build_field_specs(BLOCK, ["map_region; DROP TABLE"])

    def test_mixed_request_keeps_order_and_kinds(self):
        specs = bf.build_field_specs(
            BLOCK, ["src_evaluation_category", "map_region", "src_quality_rating"]
        )
        assert [s.field for s in specs] == [
            "src_evaluation_category",
            "map_region",
            "src_quality_rating",
        ]
        assert [s.kind for s in specs] == ["jsonb", "column", "jsonb"]


# ---------------------------------------------------------------------------
# group_doc_ids_by_value
# ---------------------------------------------------------------------------


class TestGroupDocIdsByValue:
    def test_groups_docs_by_value(self):
        rows = [
            {"doc_id": "a", "src_evaluation_category": "DE"},
            {"doc_id": "b", "src_evaluation_category": "CE"},
            {"doc_id": "c", "src_evaluation_category": "DE"},
        ]
        groups = bf.group_doc_ids_by_value(rows, "src_evaluation_category")
        assert groups == {"DE": ["a", "c"], "CE": ["b"]}

    def test_skips_none_and_empty_values(self):
        rows = [
            {"doc_id": "a", "map_region": None},
            {"doc_id": "b", "map_region": ""},
            {"doc_id": "c", "map_region": "   "},
            {"doc_id": "d", "map_region": "East Africa"},
        ]
        groups = bf.group_doc_ids_by_value(rows, "map_region")
        assert groups == {"East Africa": ["d"]}

    def test_trims_whitespace_so_variants_merge(self):
        rows = [
            {"doc_id": "a", "src_quality_rating": "Satisfactory or above"},
            {"doc_id": "b", "src_quality_rating": " Satisfactory or above "},
        ]
        groups = bf.group_doc_ids_by_value(rows, "src_quality_rating")
        assert groups == {"Satisfactory or above": ["a", "b"]}
