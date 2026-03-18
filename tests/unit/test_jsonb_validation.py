"""Tests for JSONB safety validators in schemas."""

import pytest

from ui.backend.auth.schemas import _check_jsonb_depth, _validate_jsonb


class TestCheckJsonbDepth:
    """Tests for the _check_jsonb_depth helper."""

    def test_flat_dict(self):
        """A flat dict should pass."""
        _check_jsonb_depth({"key": "value", "num": 42})

    def test_nested_within_limit(self):
        """Nesting up to 10 levels should pass."""
        obj = {"a": "leaf"}
        for _ in range(9):  # 10 levels total
            obj = {"nested": obj}
        _check_jsonb_depth(obj)  # should not raise

    def test_nested_exceeds_limit(self):
        """Nesting beyond 10 levels should raise ValueError."""
        obj = {"a": "leaf"}
        for _ in range(11):
            obj = {"nested": obj}
        with pytest.raises(ValueError, match="depth"):
            _check_jsonb_depth(obj)

    def test_list_nesting(self):
        """Lists count toward depth."""
        obj = "leaf"
        for _ in range(12):
            obj = [obj]
        with pytest.raises(ValueError, match="depth"):
            _check_jsonb_depth(obj)

    def test_mixed_nesting(self):
        """Mixed dict/list nesting within limit passes."""
        obj = {"data": [{"items": [{"value": 1}]}]}
        _check_jsonb_depth(obj)  # depth 4 — fine

    def test_none_value(self):
        """None is fine (no recursion needed)."""
        _check_jsonb_depth(None)

    def test_string_value(self):
        """A plain string is fine."""
        _check_jsonb_depth("hello")

    def test_empty_dict(self):
        """An empty dict should pass."""
        _check_jsonb_depth({})

    def test_empty_list(self):
        """An empty list should pass."""
        _check_jsonb_depth([])


class TestValidateJsonb:
    """Tests for the _validate_jsonb composite validator."""

    def test_none_passes_through(self):
        assert _validate_jsonb(None) is None

    def test_normal_dict_passes(self):
        data = {"key": "value", "nested": {"a": 1}}
        assert _validate_jsonb(data) == data

    def test_depth_exceeded_raises(self):
        deep = {"a": "leaf"}
        for _ in range(12):
            deep = {"n": deep}
        with pytest.raises(ValueError, match="depth"):
            _validate_jsonb(deep)

    def test_size_exceeded_raises(self):
        huge = {"data": "x" * 250_000}
        with pytest.raises(ValueError, match="size"):
            _validate_jsonb(huge)

    def test_at_size_limit_passes(self):
        """A payload just under the size limit should pass."""
        # 200_000 char limit — build something close but under
        data = {"data": "x" * 199_950}
        result = _validate_jsonb(data)
        assert result is data
