"""Unit tests for admin-managed API key functionality."""

import hashlib
import secrets

import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead


class TestApiKeyGeneration:
    """Test API key generation format and hashing."""

    def test_key_format_prefix(self):
        """Generated keys should start with 'el_' prefix."""
        raw_key = "el_" + secrets.token_urlsafe(32)
        assert raw_key.startswith("el_")
        assert len(raw_key) > 40  # el_ + 43 chars base64

    def test_key_hash_matches(self):
        """SHA-256 hash of the raw key should be deterministic."""
        raw_key = "el_" + secrets.token_urlsafe(32)
        h1 = hashlib.sha256(raw_key.encode()).hexdigest()
        h2 = hashlib.sha256(raw_key.encode()).hexdigest()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest is 64 chars

    def test_key_hash_differs_for_different_keys(self):
        """Different keys should produce different hashes."""
        k1 = "el_" + secrets.token_urlsafe(32)
        k2 = "el_" + secrets.token_urlsafe(32)
        h1 = hashlib.sha256(k1.encode()).hexdigest()
        h2 = hashlib.sha256(k2.encode()).hexdigest()
        assert h1 != h2

    def test_key_prefix_extraction(self):
        """Key prefix should be the first 10 characters."""
        raw_key = "el_" + secrets.token_urlsafe(32)
        prefix = raw_key[:10]
        assert len(prefix) == 10
        assert prefix.startswith("el_")

    def test_key_is_url_safe(self):
        """Generated key body should be URL-safe."""
        raw_key = "el_" + secrets.token_urlsafe(32)
        body = raw_key[3:]  # strip el_
        # URL-safe base64 uses only alphanumeric, dash, underscore
        assert all(c.isalnum() or c in "-_" for c in body)


class TestApiKeySchemas:
    """Test Pydantic schema validation."""

    def test_create_valid_label(self):
        """ApiKeyCreate accepts a valid label."""
        schema = ApiKeyCreate(label="Production pipeline")
        assert schema.label == "Production pipeline"

    def test_create_default_label(self):
        """ApiKeyCreate uses default label when none provided."""
        schema = ApiKeyCreate()
        assert schema.label == "API Key"

    def test_create_empty_label_rejected(self):
        """ApiKeyCreate rejects empty label."""
        with pytest.raises(ValidationError):
            ApiKeyCreate(label="")

    def test_create_label_max_length(self):
        """ApiKeyCreate rejects labels exceeding 255 chars."""
        with pytest.raises(ValidationError):
            ApiKeyCreate(label="x" * 256)

    def test_read_schema(self):
        """ApiKeyRead accepts valid data."""
        data = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "label": "Test key",
            "key_prefix": "el_abc12ab",
            "is_active": True,
            "created_at": "2026-01-01T00:00:00Z",
            "created_by_email": "admin@example.com",
            "last_used_at": None,
        }
        schema = ApiKeyRead(**data)
        assert schema.label == "Test key"
        assert schema.key_prefix == "el_abc12ab"

    def test_created_schema_includes_key(self):
        """ApiKeyCreated includes the full key field."""
        data = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "label": "Test key",
            "key_prefix": "el_abc12ab",
            "is_active": True,
            "created_at": "2026-01-01T00:00:00Z",
            "created_by_email": None,
            "last_used_at": None,
            "key": "el_abc12abc-full-key-here",
        }
        schema = ApiKeyCreated(**data)
        assert schema.key == "el_abc12abc-full-key-here"


class TestApiKeyCacheLogic:
    """Test cache invalidation logic."""

    def test_invalidate_resets_cache(self):
        """invalidate_cache should reset the module-level cache."""
        from ui.backend.auth import api_key_cache

        # Set cache to a known value
        api_key_cache._cache = {"some_hash"}
        assert api_key_cache._cache is not None

        api_key_cache.invalidate_cache()
        assert api_key_cache._cache is None

    def test_cache_starts_none(self):
        """Cache should start as None (not loaded)."""
        from ui.backend.auth import api_key_cache

        api_key_cache.invalidate_cache()
        assert api_key_cache._cache is None
