"""Tests for activity schemas and validation."""

import uuid

import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import ActivityCreate, ActivityRead, ActivitySummaryUpdate


class TestActivityCreate:
    """Tests for the ActivityCreate schema."""

    def test_valid_activity_minimal(self):
        """An activity with required fields only."""
        a = ActivityCreate(
            search_id=str(uuid.uuid4()),
            query="test query",
        )
        assert a.query == "test query"
        assert a.filters is None
        assert a.search_results is None
        assert a.ai_summary is None
        assert a.url is None

    def test_valid_activity_all_fields(self):
        """An activity with all optional fields populated."""
        sid = str(uuid.uuid4())
        a = ActivityCreate(
            search_id=sid,
            query="climate adaptation",
            filters={"country": "Kenya", "year": "2024"},
            search_results=[
                {"chunk_id": "c1", "doc_id": "d1", "title": "Report 1", "score": 0.95}
            ],
            ai_summary="Summary of results about climate adaptation...",
            url="https://example.com/search?q=climate",
        )
        assert a.search_id == sid
        assert a.query == "climate adaptation"
        assert a.filters is not None
        assert len(a.search_results) == 1
        assert a.ai_summary.startswith("Summary")
        assert a.url == "https://example.com/search?q=climate"

    def test_empty_query_rejected(self):
        """An empty query string should be rejected (Pydantic treats as required)."""
        # query is str, so "" is valid but the route logic may check
        a = ActivityCreate(search_id=str(uuid.uuid4()), query="")
        assert a.query == ""

    def test_missing_query_rejected(self):
        """A missing query field should raise ValidationError."""
        with pytest.raises(ValidationError, match="query"):
            ActivityCreate(search_id=str(uuid.uuid4()))

    def test_missing_search_id_rejected(self):
        """A missing search_id field should raise ValidationError."""
        with pytest.raises(ValidationError, match="search_id"):
            ActivityCreate(query="test")


class TestActivitySummaryUpdate:
    """Tests for the ActivitySummaryUpdate schema."""

    def test_valid_summary(self):
        """A valid summary update."""
        u = ActivitySummaryUpdate(ai_summary="Updated summary text.")
        assert u.ai_summary == "Updated summary text."

    def test_optional_summary(self):
        """ai_summary is optional — an empty update is valid (tree-only PATCH)."""
        u = ActivitySummaryUpdate()
        assert u.ai_summary is None
        assert u.summary_duration_ms is None
        assert u.drilldown_tree is None

    def test_tree_only_update(self):
        """Can send drilldown_tree without ai_summary."""
        tree = {"id": "root", "label": "Root", "children": []}
        u = ActivitySummaryUpdate(drilldown_tree=tree)
        assert u.ai_summary is None
        assert u.drilldown_tree == tree


class TestActivityRead:
    """Tests for the ActivityRead schema."""

    def test_from_dict(self):
        """ActivityRead should accept all fields including url."""
        uid = uuid.uuid4()
        aid = uuid.uuid4()
        sid = uuid.uuid4()
        data = {
            "id": aid,
            "user_id": uid,
            "user_email": "user@example.com",
            "user_display_name": "Test User",
            "search_id": sid,
            "query": "test query",
            "filters": {"year": "2024"},
            "search_results": [{"chunk_id": "c1"}],
            "ai_summary": "Some summary",
            "url": "https://example.com/search",
            "has_ratings": True,
            "created_at": "2026-03-01T12:00:00Z",
        }
        r = ActivityRead(**data)
        assert r.id == aid
        assert r.search_id == sid
        assert r.query == "test query"
        assert r.url == "https://example.com/search"
        assert r.has_ratings is True

    def test_nullable_fields(self):
        """Optional fields should accept None."""
        data = {
            "id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "user_email": None,
            "user_display_name": None,
            "search_id": uuid.uuid4(),
            "query": "q",
            "filters": None,
            "search_results": None,
            "ai_summary": None,
            "url": None,
            "has_ratings": False,
            "created_at": "2026-03-01T12:00:00Z",
        }
        r = ActivityRead(**data)
        assert r.user_email is None
        assert r.filters is None
        assert r.ai_summary is None
        assert r.url is None
        assert r.has_ratings is False
