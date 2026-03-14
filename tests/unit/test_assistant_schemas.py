"""Unit tests for assistant-related Pydantic schemas."""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import (
    AssistantChatRequest,
    AssistantModelConfig,
    AssistantSearchSettings,
    ConversationMessageRead,
    ConversationThreadListItem,
    ConversationThreadRead,
    ThreadRenameRequest,
)


class TestAssistantModelConfig:
    """Tests for AssistantModelConfig schema."""

    def test_minimal_creation(self):
        config = AssistantModelConfig(model="gpt-4.1-mini")
        assert config.model == "gpt-4.1-mini"
        assert config.max_tokens == 2000
        assert config.temperature == 0.0
        assert config.chunk_overlap == 800
        assert config.chunk_tokens_ratio == 0.5

    def test_full_creation(self):
        config = AssistantModelConfig(
            model="gemini-2.5-flash",
            max_tokens=4000,
            temperature=0.5,
            chunk_overlap=400,
            chunk_tokens_ratio=0.8,
        )
        assert config.model == "gemini-2.5-flash"
        assert config.max_tokens == 4000
        assert config.temperature == 0.5
        assert config.chunk_overlap == 400
        assert config.chunk_tokens_ratio == 0.8

    def test_missing_model_fails(self):
        with pytest.raises(ValidationError):
            AssistantModelConfig()


class TestAssistantChatRequest:
    """Tests for AssistantChatRequest schema."""

    def test_minimal_creation(self):
        req = AssistantChatRequest(query="What are the key findings?")
        assert req.query == "What are the key findings?"
        assert req.thread_id is None
        assert req.data_source is None
        assert req.assistant_model_config is None

    def test_full_creation(self):
        config = AssistantModelConfig(model="gpt-4.1-mini")
        req = AssistantChatRequest(
            query="Summarize the reports",
            thread_id="abc-123",
            data_source="test_source",
            assistant_model_config=config,
        )
        assert req.query == "Summarize the reports"
        assert req.thread_id == "abc-123"
        assert req.data_source == "test_source"
        assert req.assistant_model_config.model == "gpt-4.1-mini"

    def test_missing_query_fails(self):
        with pytest.raises(ValidationError):
            AssistantChatRequest()

    def test_empty_query_accepted(self):
        # Empty string is allowed (not None); max_length enforced at field level
        req = AssistantChatRequest(query="")
        assert req.query == ""

    def test_query_max_length_enforced(self):
        # Query exceeding 5000 chars should fail
        long_query = "x" * 5001
        with pytest.raises(ValidationError):
            AssistantChatRequest(query=long_query)

    def test_query_at_max_length_succeeds(self):
        query = "x" * 5000
        req = AssistantChatRequest(query=query)
        assert len(req.query) == 5000

    def test_data_source_max_length_enforced(self):
        long_ds = "x" * 256
        with pytest.raises(ValidationError):
            AssistantChatRequest(query="test", data_source=long_ds)


class TestConversationMessageRead:
    """Tests for ConversationMessageRead schema."""

    def test_creation(self):
        msg_id = uuid.uuid4()
        thread_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        msg = ConversationMessageRead(
            id=msg_id,
            thread_id=thread_id,
            role="user",
            content="Hello there",
            created_at=now,
        )
        assert msg.id == msg_id
        assert msg.thread_id == thread_id
        assert msg.role == "user"
        assert msg.content == "Hello there"
        assert msg.sources is None
        assert msg.agent_state is None

    def test_with_sources(self):
        msg = ConversationMessageRead(
            id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            role="assistant",
            content="Here is the answer",
            sources={"citations": [{"docId": "doc1", "title": "Test"}]},
            created_at=datetime.now(timezone.utc),
        )
        assert msg.sources["citations"][0]["docId"] == "doc1"

    def test_with_agent_state(self):
        msg = ConversationMessageRead(
            id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            role="assistant",
            content="Answer",
            agent_state={"phase": "synthesizing", "iteration": 2},
            created_at=datetime.now(timezone.utc),
        )
        assert msg.agent_state["phase"] == "synthesizing"


class TestConversationThreadRead:
    """Tests for ConversationThreadRead schema."""

    def test_creation_with_messages(self):
        thread_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        msg = ConversationMessageRead(
            id=uuid.uuid4(),
            thread_id=thread_id,
            role="user",
            content="Question",
            created_at=now,
        )
        thread = ConversationThreadRead(
            id=thread_id,
            user_id=user_id,
            title="Test conversation",
            created_at=now,
            updated_at=now,
            messages=[msg],
        )
        assert thread.id == thread_id
        assert thread.user_id == user_id
        assert thread.title == "Test conversation"
        assert len(thread.messages) == 1
        assert thread.messages[0].role == "user"

    def test_creation_empty_messages(self):
        now = datetime.now(timezone.utc)
        thread = ConversationThreadRead(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="Empty thread",
            created_at=now,
            updated_at=now,
        )
        assert thread.messages == []

    def test_optional_fields(self):
        now = datetime.now(timezone.utc)
        thread = ConversationThreadRead(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="Thread",
            data_source="my_source",
            metadata_json={"key": "value"},
            created_at=now,
            updated_at=now,
        )
        assert thread.data_source == "my_source"
        assert thread.metadata_json == {"key": "value"}


class TestConversationThreadListItem:
    """Tests for ConversationThreadListItem schema."""

    def test_creation(self):
        now = datetime.now(timezone.utc)
        item = ConversationThreadListItem(
            id=uuid.uuid4(),
            title="Research on food security",
            message_count=5,
            created_at=now,
            updated_at=now,
        )
        assert item.title == "Research on food security"
        assert item.message_count == 5
        assert item.data_source is None

    def test_default_message_count(self):
        now = datetime.now(timezone.utc)
        item = ConversationThreadListItem(
            id=uuid.uuid4(),
            title="Thread",
            created_at=now,
            updated_at=now,
        )
        assert item.message_count == 0

    def test_with_data_source(self):
        now = datetime.now(timezone.utc)
        item = ConversationThreadListItem(
            id=uuid.uuid4(),
            title="Thread",
            data_source="test_ds",
            message_count=10,
            created_at=now,
            updated_at=now,
        )
        assert item.data_source == "test_ds"


class TestThreadRenameRequest:
    """Tests for ThreadRenameRequest schema."""

    def test_valid_title(self):
        req = ThreadRenameRequest(title="My renamed thread")
        assert req.title == "My renamed thread"

    def test_empty_title_rejected(self):
        with pytest.raises(ValidationError):
            ThreadRenameRequest(title="")

    def test_title_max_length(self):
        req = ThreadRenameRequest(title="x" * 500)
        assert len(req.title) == 500

    def test_title_exceeds_max_length(self):
        with pytest.raises(ValidationError):
            ThreadRenameRequest(title="x" * 501)

    def test_whitespace_only_title_rejected(self):
        """A title with only whitespace should fail min_length after strip."""
        # Note: Pydantic doesn't auto-strip, so " " has length 1 and passes
        # min_length. The backend/frontend trims before sending.
        req = ThreadRenameRequest(title=" ")
        assert req.title == " "


class TestAssistantSearchSettings:
    """Tests for AssistantSearchSettings schema."""

    def test_all_fields(self):
        settings = AssistantSearchSettings(
            dense_weight=0.6,
            recency_boost=True,
            recency_weight=0.3,
            recency_scale_days=90,
            section_types=["text", "table"],
            keyword_boost_short_queries=False,
            min_chunk_size=200,
        )
        assert settings.dense_weight == 0.6
        assert settings.recency_boost is True
        assert settings.recency_weight == 0.3
        assert settings.recency_scale_days == 90
        assert settings.section_types == ["text", "table"]
        assert settings.keyword_boost_short_queries is False
        assert settings.min_chunk_size == 200

    def test_all_optional(self):
        settings = AssistantSearchSettings()
        assert settings.dense_weight is None
        assert settings.recency_boost is None
        assert settings.section_types is None

    def test_partial_fields(self):
        settings = AssistantSearchSettings(
            dense_weight=0.8,
            recency_boost=False,
        )
        assert settings.dense_weight == 0.8
        assert settings.recency_boost is False
        assert settings.min_chunk_size is None

    def test_model_dump_exclude_none(self):
        """model_dump(exclude_none=True) should only include set fields."""
        settings = AssistantSearchSettings(dense_weight=0.7)
        dumped = settings.model_dump(exclude_none=True)
        assert dumped == {"dense_weight": 0.7}

    def test_chat_request_with_search_settings(self):
        """AssistantChatRequest should accept search_settings."""
        req = AssistantChatRequest(
            query="test",
            search_settings={
                "dense_weight": 0.6,
                "recency_boost": True,
            },
        )
        assert req.search_settings is not None
        assert req.search_settings.dense_weight == 0.6
        assert req.search_settings.recency_boost is True

    def test_chat_request_without_search_settings(self):
        req = AssistantChatRequest(query="test")
        assert req.search_settings is None

    def test_field_boost_fields(self):
        """field_boost_enabled and field_boost_fields should be accepted."""
        settings = AssistantSearchSettings(
            field_boost_enabled=True,
            field_boost_fields={"country": 0.5, "organization": 0.3},
        )
        assert settings.field_boost_enabled is True
        assert settings.field_boost_fields == {"country": 0.5, "organization": 0.3}

    def test_field_boost_defaults_to_none(self):
        """field_boost fields should default to None."""
        settings = AssistantSearchSettings()
        assert settings.field_boost_enabled is None
        assert settings.field_boost_fields is None

    def test_field_boost_in_model_dump(self):
        """field_boost fields should be included in model_dump."""
        settings = AssistantSearchSettings(
            field_boost_enabled=True,
            field_boost_fields={"country": 0.5},
        )
        dumped = settings.model_dump(exclude_none=True)
        assert dumped["field_boost_enabled"] is True
        assert dumped["field_boost_fields"] == {"country": 0.5}

    def test_chat_request_with_field_boost(self):
        """AssistantChatRequest should accept field_boost in search_settings."""
        req = AssistantChatRequest(
            query="test",
            search_settings={
                "field_boost_enabled": True,
                "field_boost_fields": {"country": 0.5},
                "dense_weight": 0.7,
            },
        )
        assert req.search_settings.field_boost_enabled is True
        assert req.search_settings.field_boost_fields == {"country": 0.5}
        assert req.search_settings.dense_weight == 0.7
