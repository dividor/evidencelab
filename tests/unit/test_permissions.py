"""Unit tests for the permissions service."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ui.backend.services.permissions import filter_datasources


class TestFilterDatasources:
    """Tests for the filter_datasources helper function."""

    def test_no_filtering_when_allowed_is_none(self):
        ds = {"A": {"data_subdir": "a"}, "B": {"data_subdir": "b"}}
        result = filter_datasources(ds, None)
        assert result == ds

    def test_no_filtering_when_allowed_is_empty_set(self):
        ds = {"A": {"data_subdir": "a"}, "B": {"data_subdir": "b"}}
        result = filter_datasources(ds, set())
        assert result == ds

    def test_filters_to_allowed_keys(self):
        ds = {
            "A": {"data_subdir": "a"},
            "B": {"data_subdir": "b"},
            "C": {"data_subdir": "c"},
        }
        result = filter_datasources(ds, {"A", "C"})
        assert set(result.keys()) == {"A", "C"}
        assert "B" not in result

    def test_missing_keys_dont_cause_errors(self):
        ds = {"A": {"data_subdir": "a"}}
        result = filter_datasources(ds, {"A", "Z"})
        assert set(result.keys()) == {"A"}

    def test_empty_datasources_returns_empty(self):
        result = filter_datasources({}, {"A"})
        assert result == {}

    def test_preserves_original_dict(self):
        ds = {"A": {"data_subdir": "a"}, "B": {"data_subdir": "b"}}
        original_keys = set(ds.keys())
        filter_datasources(ds, {"A"})
        # Original dict not mutated
        assert set(ds.keys()) == original_keys
