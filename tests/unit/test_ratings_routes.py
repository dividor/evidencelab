"""Tests for ratings route helpers."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from ui.backend.routes.ratings import _rating_to_read

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_rating(**overrides):
    """Create a mock UserRating ORM object."""
    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "rating_type": "search_result",
        "reference_id": str(uuid.uuid4()),
        "item_id": None,
        "score": 4,
        "comment": None,
        "context": None,
        "url": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_user(**overrides):
    """Create a mock User object."""
    defaults = {
        "id": uuid.uuid4(),
        "email": "user@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(overrides)
    ns = SimpleNamespace(**defaults)
    # Add full_name property to mimic the ORM model
    parts = [p for p in (ns.first_name, ns.last_name) if p]
    ns.full_name = " ".join(parts) if parts else None
    return ns


# ---------------------------------------------------------------------------
# _rating_to_read
# ---------------------------------------------------------------------------


class TestRatingToRead:
    """Tests for the _rating_to_read helper."""

    def test_basic_conversion(self):
        """Converts ORM object to RatingRead with user info."""
        user = _make_user()
        rating = _make_rating(user_id=user.id, score=5, comment="Great result")
        result = _rating_to_read(rating, user)
        assert result.user_email == "user@example.com"
        assert result.user_display_name == "Test User"
        assert result.score == 5
        assert result.comment == "Great result"
        assert result.rating_type == "search_result"

    def test_without_user(self):
        """Works when user is None (e.g. deleted user)."""
        rating = _make_rating()
        result = _rating_to_read(rating, None)
        assert result.user_email is None
        assert result.user_display_name is None
        assert result.score == 4

    def test_preserves_context(self):
        """Context dict passes through to RatingRead."""
        ctx = {"query": "test", "filters": {"year": "2024"}}
        rating = _make_rating(context=ctx)
        result = _rating_to_read(rating)
        assert result.context == ctx

    def test_preserves_item_id(self):
        """item_id for chunk-level ratings passes through."""
        rating = _make_rating(item_id="chunk-abc-123")
        result = _rating_to_read(rating)
        assert result.item_id == "chunk-abc-123"

    def test_preserves_url(self):
        """URL passes through to RatingRead."""
        rating = _make_rating(url="https://example.com/search?q=test")
        result = _rating_to_read(rating)
        assert result.url == "https://example.com/search?q=test"

    def test_all_rating_types(self):
        """All valid rating types convert correctly."""
        for rtype in (
            "search_result",
            "ai_summary",
            "doc_summary",
            "taxonomy",
            "heatmap",
        ):
            rating = _make_rating(rating_type=rtype)
            result = _rating_to_read(rating)
            assert result.rating_type == rtype
