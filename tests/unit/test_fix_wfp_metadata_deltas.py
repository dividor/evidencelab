"""Unit tests for the WFP metadata reconciliation helpers.

Locks in the safety rails that make re-applying the corrected evaluation
sheet safe: blank cells never null good data, ``'; '``-list fields never
silently drop tokens, and known sheet typos are scrubbed before writing.
"""

import importlib.util
import math
from pathlib import Path

import pytest

# The script lives under scripts/fixes/ (not a package); import it by path.
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "fixes"
    / "fix_wfp_metadata_deltas.py"
)
_spec = importlib.util.spec_from_file_location("fix_wfp_metadata_deltas", _SCRIPT_PATH)
fix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fix)


# Reusable specs matching the WFP sheet layout.
REGION = fix.FieldSpec("map_region", "Region", False, True)
COUNTRY = fix.FieldSpec("map_country", "Country", True, True)
TITLE = fix.FieldSpec("map_title", "Title evaluation", True, False)
SPECS = [REGION, COUNTRY, TITLE]


@pytest.mark.unit
class TestNormalizeCell:
    def test_none_is_none(self):
        assert fix.normalize_cell(None) is None

    def test_nan_is_none(self):
        assert fix.normalize_cell(math.nan) is None

    def test_blank_string_is_none(self):
        assert fix.normalize_cell("   ") is None

    def test_integral_float_year_becomes_int_string(self):
        assert fix.normalize_cell(2024.0) == "2024"

    def test_int_id_becomes_string(self):
        assert fix.normalize_cell(33) == "33"

    def test_trims_whitespace(self):
        assert fix.normalize_cell("  Asia  ") == "Asia"


@pytest.mark.unit
class TestScrubValue:
    def test_known_typo_is_fixed(self):
        assert fix.scrub_value("Repubic of Türkiye") == "Republic of Türkiye"

    def test_typo_fixed_inside_list(self):
        assert (
            fix.scrub_value("Egypt; Repubic of Türkiye") == "Egypt; Republic of Türkiye"
        )

    def test_clean_value_passes_through(self):
        assert fix.scrub_value("Egypt; Kenya") == "Egypt; Kenya"


@pytest.mark.unit
class TestTokenLoss:
    def test_dropping_a_token_is_loss(self):
        assert fix.is_token_loss("A; B; C", "A; B") is True

    def test_rename_same_count_is_not_loss(self):
        # Laos -> Lao People's Democratic Republic: 1 token -> 1 token.
        assert fix.is_token_loss("Laos", "Lao People's Democratic Republic") is False

    def test_gaining_tokens_is_not_loss(self):
        # Placeholder region -> real multi-region list.
        assert fix.is_token_loss("Office of Evaluation", "Asia; Africa; LAC") is False


@pytest.mark.unit
class TestBuildTargets:
    def test_builds_scrubbed_targets_and_skips_blanks(self):
        records = [
            {
                "Id": 33,
                "Region": "Asia and the Pacific",
                "Country": "Repubic of Türkiye",
                "Title evaluation": "  Endline eval  ",
            }
        ]
        targets = fix.build_targets(records, SPECS)
        assert targets["33"]["map_region"] == "Asia and the Pacific"
        # typo scrubbed, whitespace trimmed
        assert targets["33"]["map_country"] == "Republic of Türkiye"
        assert targets["33"]["map_title"] == "Endline eval"

    def test_blank_cell_not_recorded(self):
        records = [{"Id": 1, "Region": None, "Country": "Kenya"}]
        targets = fix.build_targets(records, SPECS)
        assert "map_region" not in targets["1"]
        assert targets["1"]["map_country"] == "Kenya"

    def test_first_non_null_wins_for_duplicate_id(self):
        records = [
            {"Id": 5, "Region": None},
            {"Id": 5, "Region": "Western and Central Africa"},
        ]
        targets = fix.build_targets(records, SPECS)
        assert targets["5"]["map_region"] == "Western and Central Africa"

    def test_row_without_id_is_ignored(self):
        records = [{"Id": None, "Region": "Asia"}]
        assert fix.build_targets(records, SPECS) == {}


@pytest.mark.unit
class TestComputeCorrections:
    def test_changed_field_is_recorded_unchanged_is_not(self):
        docs = [
            fix.DocRow(
                "d1",
                "33",
                {"map_region": "Office of Evaluation", "map_country": "Laos"},
            )
        ]
        targets = {"33": {"map_region": "Asia", "map_country": "Laos"}}
        corrections, skips = fix.compute_corrections(docs, targets, SPECS)
        assert corrections == {"d1": {"map_region": ("Office of Evaluation", "Asia")}}
        assert skips == []

    def test_token_loss_is_skipped_and_logged(self):
        docs = [fix.DocRow("d2", "1", {"map_country": "Egypt; Kenya; Sudan"})]
        targets = {"1": {"map_country": "Egypt; Kenya"}}
        corrections, skips = fix.compute_corrections(docs, targets, SPECS)
        assert corrections == {}
        assert skips == [("d2", "map_country", "Egypt; Kenya; Sudan", "Egypt; Kenya")]

    def test_doc_without_matching_sheet_id_untouched(self):
        docs = [fix.DocRow("d3", "999", {"map_region": "X"})]
        corrections, skips = fix.compute_corrections(
            docs, {"1": {"map_region": "Y"}}, SPECS
        )
        assert corrections == {} and skips == []

    def test_null_current_value_is_filled(self):
        docs = [fix.DocRow("d4", "7", {"map_region": None})]
        corrections, _ = fix.compute_corrections(
            docs, {"7": {"map_region": "Asia"}}, SPECS
        )
        assert corrections == {"d4": {"map_region": (None, "Asia")}}


@pytest.mark.unit
class TestConfigHelpers:
    CONFIG = {
        "datasources": {
            "WFP Evaluation Reports": {
                "data_subdir": "wfp",
                "field_mapping": {
                    "region": "Region",
                    "country": "Country",
                    "organization": "fixed_value:WFP",
                },
                "src_field_mapping": {"src_quality_rating": "Quality rating"},
            }
        }
    }

    def test_resolve_by_subdir(self):
        subdir, block = fix.resolve_source(self.CONFIG, "wfp")
        assert subdir == "wfp" and "field_mapping" in block

    def test_resolve_by_key(self):
        subdir, _ = fix.resolve_source(self.CONFIG, "WFP Evaluation Reports")
        assert subdir == "wfp"

    def test_unknown_source_raises(self):
        with pytest.raises(SystemExit):
            fix.resolve_source(self.CONFIG, "nope")

    def test_build_specs_maps_columns_and_flags(self):
        _subdir, block = fix.resolve_source(self.CONFIG, "wfp")
        specs = fix.build_specs(
            block, ["map_region", "map_country", "src_quality_rating"]
        )
        by_col = {s.db_column: s for s in specs}
        assert by_col["map_region"].sheet_column == "Region"
        assert by_col["map_region"].on_chunks is False
        assert by_col["map_country"].on_chunks is True
        assert by_col["map_country"].is_list is True
        assert by_col["src_quality_rating"].sheet_column == "Quality rating"

    def test_build_specs_skips_fixed_value(self):
        _subdir, block = fix.resolve_source(self.CONFIG, "wfp")
        specs = fix.build_specs(block, ["map_organization"])
        assert specs == []

    def test_build_specs_rejects_illegal_identifier(self):
        _subdir, block = fix.resolve_source(self.CONFIG, "wfp")
        with pytest.raises(SystemExit):
            fix.build_specs(block, ["map_region; DROP TABLE"])


@pytest.mark.unit
class TestFilterSpecsByColumns:
    def test_keeps_existing_drops_missing(self):
        # map_country absent from the table -> dropped, not crashed on.
        kept, dropped = fix.filter_specs_by_columns(
            SPECS, available={"map_region", "map_title"}
        )
        assert {s.db_column for s in kept} == {"map_region", "map_title"}
        assert dropped == ["map_country"]

    def test_all_present(self):
        kept, dropped = fix.filter_specs_by_columns(
            SPECS, available={"map_region", "map_country", "map_title"}
        )
        assert len(kept) == 3 and dropped == []
