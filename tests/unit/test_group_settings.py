"""Tests for per-group search settings: schema validation and merge logic."""

from types import SimpleNamespace

import pytest

from ui.backend.auth.schemas import SearchSettings


class TestSearchSettingsSchema:
    """Test the SearchSettings Pydantic schema."""

    def test_valid_partial_settings(self):
        """Partial settings should validate — only set keys are present."""
        s = SearchSettings(denseWeight=0.5, rerank=False)
        assert s.denseWeight == 0.5
        assert s.rerank is False
        assert s.recencyBoost is None

    def test_empty_settings(self):
        """Empty settings should be valid (all fields None)."""
        s = SearchSettings()
        assert s.denseWeight is None
        assert s.rerank is None
        assert s.sectionTypes is None

    def test_full_settings(self):
        """All fields can be set at once."""
        s = SearchSettings(
            denseWeight=0.6,
            rerank=True,
            recencyBoost=True,
            recencyWeight=0.2,
            recencyScaleDays=180,
            sectionTypes=["findings", "conclusions"],
            keywordBoostShortQueries=False,
            minChunkSize=200,
            semanticHighlighting=False,
            autoMinScore=True,
            deduplicate=False,
            fieldBoost=True,
            fieldBoostFields={"country": 1.0, "organization": 0.5},
        )
        assert s.denseWeight == 0.6
        assert s.sectionTypes == ["findings", "conclusions"]
        assert s.fieldBoostFields == {"country": 1.0, "organization": 0.5}

    def test_invalid_type_rejected(self):
        """Invalid types should raise validation errors."""
        with pytest.raises(Exception):
            SearchSettings(denseWeight="not-a-number")  # type: ignore

    def test_field_boost_fields_dict_validation(self):
        """fieldBoostFields must be a dict of str -> float."""
        s = SearchSettings(fieldBoostFields={"country": 1.5})
        assert s.fieldBoostFields == {"country": 1.5}


class TestMergeGroupSettings:
    """Test the _merge_group_settings helper from routes/users.py."""

    def _make_group(self, settings):
        """Create a mock group object with search_settings attribute."""
        return SimpleNamespace(search_settings=settings)

    def test_empty_list(self):
        from ui.backend.routes.users import _merge_group_settings

        result = _merge_group_settings([])
        assert result == {}

    def test_single_group_no_settings(self):
        from ui.backend.routes.users import _merge_group_settings

        result = _merge_group_settings([self._make_group(None)])
        assert result == {}

    def test_single_group_with_settings(self):
        from ui.backend.routes.users import _merge_group_settings

        result = _merge_group_settings(
            [self._make_group({"denseWeight": 0.5, "rerank": False})]
        )
        assert result == {"denseWeight": 0.5, "rerank": False}

    def test_multi_group_first_wins(self):
        """First non-null value per key wins (groups ordered by name)."""
        from ui.backend.routes.users import _merge_group_settings

        groups = [
            self._make_group({"denseWeight": 0.3}),  # group "Analysts"
            self._make_group({"denseWeight": 0.8, "rerank": False}),  # group "Default"
        ]
        result = _merge_group_settings(groups)
        # denseWeight=0.3 from first group wins; rerank=False from second group
        assert result == {"denseWeight": 0.3, "rerank": False}

    def test_multi_group_skips_none_settings(self):
        """Groups with no settings are skipped."""
        from ui.backend.routes.users import _merge_group_settings

        groups = [
            self._make_group(None),
            self._make_group({"rerank": True}),
        ]
        result = _merge_group_settings(groups)
        assert result == {"rerank": True}

    def test_multi_group_empty_dict(self):
        """Groups with empty dict are skipped (no keys to merge)."""
        from ui.backend.routes.users import _merge_group_settings

        groups = [
            self._make_group({}),
            self._make_group({"deduplicate": False}),
        ]
        result = _merge_group_settings(groups)
        assert result == {"deduplicate": False}
