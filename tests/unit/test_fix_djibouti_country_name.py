"""Unit tests for the Dibouti -> Djibouti country fix helpers.

Locks in the token-precise rewrite logic so a future tweak can't
accidentally touch an already-correct 'Djibouti' token or rewrite a
body-text mention.
"""

import importlib.util
from pathlib import Path

import pytest

# Load the script as a module — it lives under scripts/fixes/, not
# under a package, so we import via spec.
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "fixes"
    / "fix_djibouti_country_name.py"
)
_spec = importlib.util.spec_from_file_location(
    "fix_djibouti_country_name", _SCRIPT_PATH
)
fix_dji = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fix_dji)

# The exact value carried by the one mis-tagged document, doc_id
# 201f6a29-12a6-55a8-860c-041116041af6.
_CORRUPT = "Chad; Honduras; State of Palestine; United Arab Emirates; Dibouti; Nepal"
_FIXED = "Chad; Honduras; State of Palestine; United Arab Emirates; Djibouti; Nepal"


@pytest.mark.unit
class TestRewriteCountryString:
    """String form: '; '-separated country lists."""

    def test_real_corrupt_value_is_rewritten(self):
        assert fix_dji.rewrite_country(_CORRUPT) == _FIXED

    def test_bare_token_in_list_is_rewritten(self):
        assert fix_dji.rewrite_country("Ethiopia; Dibouti") == "Ethiopia; Djibouti"

    def test_bare_token_alone_is_rewritten(self):
        assert fix_dji.rewrite_country("Dibouti") == "Djibouti"

    def test_already_correct_value_is_unchanged(self):
        # Idempotence — value must come back identical (same object even).
        v = "Ethiopia; Djibouti"
        assert fix_dji.rewrite_country(v) is v

    def test_djibouti_token_is_not_touched(self):
        # 'Dibouti' is not a substring of 'Djibouti'; the correct token
        # must be left alone.
        v = "Kenya; Djibouti; Somalia"
        assert fix_dji.rewrite_country(v) is v

    def test_body_text_mention_in_value_is_not_rewritten(self):
        # Only an EXACT 'Dibouti' token is rewritten. A token like
        # 'Dibouti port' would not match because its stripped form
        # != 'Dibouti'.
        v = "Dibouti port context"
        assert fix_dji.rewrite_country(v) is v

    def test_multi_position_token(self):
        assert (
            fix_dji.rewrite_country("Dibouti; Kenya; Ethiopia")
            == "Djibouti; Kenya; Ethiopia"
        )

    def test_empty_and_none_passthrough(self):
        assert fix_dji.rewrite_country("") == ""
        assert fix_dji.rewrite_country(None) is None


@pytest.mark.unit
class TestRewriteCountryList:
    """List form: some Qdrant payloads store countries as a list."""

    def test_bare_token_in_list_is_rewritten(self):
        assert fix_dji.rewrite_country(["Ethiopia", "Dibouti"]) == [
            "Ethiopia",
            "Djibouti",
        ]

    def test_already_correct_list_is_unchanged(self):
        v = ["Ethiopia", "Djibouti"]
        assert fix_dji.rewrite_country(v) is v

    def test_list_without_dibouti_is_unchanged(self):
        v = ["Bangladesh", "Chad", "Iraq"]
        assert fix_dji.rewrite_country(v) is v

    def test_non_string_items_in_list_are_passed_through(self):
        # Defensive — never crash on weird payload contents, just leave
        # non-string items alone.
        v = ["Dibouti", None, 42]
        assert fix_dji.rewrite_country(v) == ["Djibouti", None, 42]


@pytest.mark.unit
class TestNeedsRewrite:
    def test_true_for_bare_token(self):
        assert fix_dji.needs_rewrite("Ethiopia; Dibouti") is True

    def test_true_for_real_corrupt_value(self):
        assert fix_dji.needs_rewrite(_CORRUPT) is True

    def test_false_for_correct_token(self):
        assert fix_dji.needs_rewrite("Djibouti") is False

    def test_false_for_unrelated_value(self):
        assert fix_dji.needs_rewrite("Iraq; Lebanon") is False

    def test_false_for_none(self):
        assert fix_dji.needs_rewrite(None) is False
