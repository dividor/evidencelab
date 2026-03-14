"""Unit tests for saved research schemas and route helpers."""

import uuid

import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import (
    SavedResearchCreate,
    SavedResearchListItem,
    SavedResearchRead,
    SavedResearchUpdate,
)
from ui.backend.routes.research import _count_nodes

# ---------------------------------------------------------------------------
# Helper: _count_nodes
# ---------------------------------------------------------------------------


class TestCountNodes:
    """Tests for the recursive _count_nodes helper."""

    def test_single_root(self):
        """A root with no children counts as 1."""
        tree = {"id": "root", "label": "Root", "children": []}
        assert _count_nodes(tree) == 1

    def test_root_with_children(self):
        """Root + 2 children = 3 nodes."""
        tree = {
            "id": "root",
            "label": "Root",
            "children": [
                {"id": "c1", "label": "Child 1", "children": []},
                {"id": "c2", "label": "Child 2", "children": []},
            ],
        }
        assert _count_nodes(tree) == 3

    def test_nested_tree(self):
        """Root → child → grandchild = 3 nodes."""
        tree = {
            "id": "root",
            "label": "Root",
            "children": [
                {
                    "id": "c1",
                    "label": "Child",
                    "children": [
                        {"id": "gc1", "label": "Grandchild", "children": []},
                    ],
                },
            ],
        }
        assert _count_nodes(tree) == 3

    def test_complex_tree(self):
        """Root with mixed nesting: root(2 children, 1 has 2 grandchildren) = 5."""
        tree = {
            "id": "root",
            "label": "Root",
            "children": [
                {
                    "id": "c1",
                    "label": "Child 1",
                    "children": [
                        {"id": "gc1", "label": "GC1", "children": []},
                        {"id": "gc2", "label": "GC2", "children": []},
                    ],
                },
                {"id": "c2", "label": "Child 2", "children": []},
            ],
        }
        assert _count_nodes(tree) == 5

    def test_missing_children_key(self):
        """A node without a children key counts as 1."""
        tree = {"id": "root", "label": "Root"}
        assert _count_nodes(tree) == 1

    def test_empty_dict(self):
        """An empty dict counts as 1 (the node itself)."""
        assert _count_nodes({}) == 1


# ---------------------------------------------------------------------------
# SavedResearchCreate
# ---------------------------------------------------------------------------


class TestSavedResearchCreate:
    """Tests for the SavedResearchCreate schema."""

    SAMPLE_TREE = {
        "id": "root",
        "label": "Climate adaptation",
        "summary": "Summary text",
        "prompt": "Summarize...",
        "results": [],
        "children": [],
    }

    def test_valid_minimal(self):
        """Minimal valid payload with required fields."""
        sr = SavedResearchCreate(
            title="My Research",
            query="climate adaptation",
            drilldown_tree=self.SAMPLE_TREE,
        )
        assert sr.title == "My Research"
        assert sr.query == "climate adaptation"
        assert sr.filters is None
        assert sr.data_source is None
        assert sr.drilldown_tree["id"] == "root"

    def test_valid_all_fields(self):
        """All fields populated."""
        sr = SavedResearchCreate(
            title="Full Research",
            query="girls health",
            filters={"country": ["Kenya"]},
            data_source="un_reports",
            drilldown_tree=self.SAMPLE_TREE,
        )
        assert sr.filters == {"country": ["Kenya"]}
        assert sr.data_source == "un_reports"

    def test_missing_title_rejected(self):
        """Missing title should raise ValidationError."""
        with pytest.raises(ValidationError, match="title"):
            SavedResearchCreate(
                query="test",
                drilldown_tree=self.SAMPLE_TREE,
            )

    def test_missing_query_rejected(self):
        """Missing query should raise ValidationError."""
        with pytest.raises(ValidationError, match="query"):
            SavedResearchCreate(
                title="Title",
                drilldown_tree=self.SAMPLE_TREE,
            )

    def test_missing_tree_rejected(self):
        """Missing drilldown_tree should raise ValidationError."""
        with pytest.raises(ValidationError, match="drilldown_tree"):
            SavedResearchCreate(
                title="Title",
                query="test",
            )

    def test_title_max_length(self):
        """title exceeding 500 chars should be rejected."""
        with pytest.raises(ValidationError, match="title"):
            SavedResearchCreate(
                title="x" * 501,
                query="test",
                drilldown_tree=self.SAMPLE_TREE,
            )

    def test_query_max_length(self):
        """query exceeding 5000 chars should be rejected."""
        with pytest.raises(ValidationError, match="query"):
            SavedResearchCreate(
                title="Title",
                query="x" * 5001,
                drilldown_tree=self.SAMPLE_TREE,
            )

    def test_tree_depth_limit(self):
        """Deeply nested tree should be rejected (exceeds JSONB depth of 10)."""
        deep = {"id": "leaf", "label": "L", "children": []}
        for _ in range(14):
            deep = {"id": "n", "label": "N", "children": [deep]}
        with pytest.raises(ValidationError, match="depth"):
            SavedResearchCreate(
                title="Title",
                query="test",
                drilldown_tree=deep,
            )

    def test_tree_size_limit(self):
        """Extremely large tree payload should be rejected."""
        huge_tree = {
            "id": "root",
            "label": "Root",
            "summary": "x" * 11_000_000,
            "children": [],
        }
        with pytest.raises(ValidationError, match="size"):
            SavedResearchCreate(
                title="Title",
                query="test",
                drilldown_tree=huge_tree,
            )

    def test_filters_jsonb_depth_limit(self):
        """Deeply nested filters dict should be rejected."""
        deep = {"a": "leaf"}
        for _ in range(14):
            deep = {"nested": deep}
        with pytest.raises(ValidationError, match="depth"):
            SavedResearchCreate(
                title="Title",
                query="test",
                filters=deep,
                drilldown_tree=self.SAMPLE_TREE,
            )

    def test_normal_tree_accepted(self):
        """A reasonably nested tree should be accepted."""
        tree = {
            "id": "root",
            "label": "Root",
            "summary": "Root summary",
            "children": [
                {
                    "id": "c1",
                    "label": "Child 1",
                    "summary": "Child summary",
                    "children": [
                        {
                            "id": "gc1",
                            "label": "Grandchild",
                            "summary": "GC summary",
                            "children": [],
                        }
                    ],
                }
            ],
        }
        sr = SavedResearchCreate(title="Title", query="test", drilldown_tree=tree)
        assert sr.drilldown_tree["id"] == "root"


# ---------------------------------------------------------------------------
# SavedResearchUpdate
# ---------------------------------------------------------------------------


class TestSavedResearchUpdate:
    """Tests for the SavedResearchUpdate schema."""

    def test_all_optional(self):
        """An empty update is valid — nothing to change."""
        u = SavedResearchUpdate()
        assert u.title is None
        assert u.drilldown_tree is None
        assert u.filters is None

    def test_title_only(self):
        """Can update just the title."""
        u = SavedResearchUpdate(title="New Title")
        assert u.title == "New Title"
        assert u.drilldown_tree is None

    def test_tree_only(self):
        """Can update just the tree."""
        tree = {"id": "root", "label": "Updated", "children": []}
        u = SavedResearchUpdate(drilldown_tree=tree)
        assert u.drilldown_tree["label"] == "Updated"

    def test_title_max_length(self):
        """title exceeding 500 chars should be rejected."""
        with pytest.raises(ValidationError, match="title"):
            SavedResearchUpdate(title="x" * 501)

    def test_tree_depth_limit(self):
        """Deeply nested tree should be rejected."""
        deep = {"id": "leaf", "children": []}
        for _ in range(14):
            deep = {"id": "n", "children": [deep]}
        with pytest.raises(ValidationError, match="depth"):
            SavedResearchUpdate(drilldown_tree=deep)


# ---------------------------------------------------------------------------
# SavedResearchRead
# ---------------------------------------------------------------------------


class TestSavedResearchRead:
    """Tests for the SavedResearchRead schema."""

    def test_from_dict(self):
        """Full read representation."""
        rid = uuid.uuid4()
        uid = uuid.uuid4()
        tree = {"id": "root", "label": "Root", "children": []}
        r = SavedResearchRead(
            id=rid,
            user_id=uid,
            title="My Research",
            query="test query",
            filters=None,
            data_source="un_reports",
            drilldown_tree=tree,
            created_at="2026-03-01T12:00:00Z",
            updated_at="2026-03-01T12:00:00Z",
        )
        assert r.id == rid
        assert r.user_id == uid
        assert r.title == "My Research"
        assert r.drilldown_tree["id"] == "root"

    def test_nullable_fields(self):
        """Optional fields accept None."""
        r = SavedResearchRead(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="T",
            query="q",
            filters=None,
            data_source=None,
            drilldown_tree={},
            created_at="2026-03-01T12:00:00Z",
            updated_at="2026-03-01T12:00:00Z",
        )
        assert r.filters is None
        assert r.data_source is None


# ---------------------------------------------------------------------------
# SavedResearchListItem
# ---------------------------------------------------------------------------


class TestSavedResearchListItem:
    """Tests for the SavedResearchListItem schema (compact list view)."""

    def test_from_dict(self):
        """List item with node_count."""
        item = SavedResearchListItem(
            id=uuid.uuid4(),
            title="Research A",
            query="query A",
            data_source="un_reports",
            node_count=5,
            created_at="2026-03-01T12:00:00Z",
            updated_at="2026-03-02T12:00:00Z",
        )
        assert item.title == "Research A"
        assert item.node_count == 5

    def test_default_node_count(self):
        """node_count defaults to 0."""
        item = SavedResearchListItem(
            id=uuid.uuid4(),
            title="Research B",
            query="query B",
            created_at="2026-03-01T12:00:00Z",
            updated_at="2026-03-01T12:00:00Z",
        )
        assert item.node_count == 0

    def test_nullable_data_source(self):
        """data_source is nullable."""
        item = SavedResearchListItem(
            id=uuid.uuid4(),
            title="Research C",
            query="query C",
            data_source=None,
            created_at="2026-03-01T12:00:00Z",
            updated_at="2026-03-01T12:00:00Z",
        )
        assert item.data_source is None
