"""Pydantic schemas for user authentication and permissions."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi_users import schemas
from pydantic import BaseModel, Field, computed_field, field_validator

# ---------------------------------------------------------------------------
# JSONB safety helpers
# ---------------------------------------------------------------------------

_MAX_JSONB_DEPTH = 10
# Cap on JSONB-bound payloads when serialised (≈1 MB; under the 2 MB request-body cap).
_MAX_JSONB_SIZE = 1_000_000


def _check_jsonb_depth(
    obj: Any, depth: int = 0, max_depth: int = _MAX_JSONB_DEPTH
) -> None:
    """Raise ValueError when *obj* exceeds the allowed nesting depth."""
    if depth > max_depth:
        raise ValueError(f"JSONB nesting exceeds maximum depth of {max_depth}")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_jsonb_depth(v, depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            _check_jsonb_depth(item, depth + 1, max_depth)


def _validate_jsonb(v: Any) -> Any:
    """Validate a JSONB-bound value for depth and approximate size."""
    if v is None:
        return v
    _check_jsonb_depth(v)
    import json

    if len(json.dumps(v, default=str)) > _MAX_JSONB_SIZE:
        raise ValueError(
            f"JSONB payload exceeds maximum size of {_MAX_JSONB_SIZE} characters"
        )
    return v


# ---------------------------------------------------------------------------
# fastapi-users schemas (registration, login, profile)
# ---------------------------------------------------------------------------


def _clean_name_field(v: Optional[str]) -> Optional[str]:
    """Strip whitespace from name fields; treat blank as None."""
    if v is not None:
        v = v.strip()
        if len(v) == 0:
            return None
    return v


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Public user representation returned by read endpoints."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @computed_field  # type: ignore[misc]
    @property
    def display_name(self) -> Optional[str]:
        """Backward-compatible computed full name."""
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) if parts else None


class UserCreate(schemas.BaseUserCreate):
    """Fields accepted when registering a new user."""

    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        return _clean_name_field(v)


class AdminUserCreate(BaseModel):
    """Payload for admin-initiated user creation (no email verification)."""

    email: str = Field(..., max_length=320)
    password: str = Field(..., max_length=128)
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        return _clean_name_field(v)


class UserUpdate(schemas.BaseUserUpdate):
    """Fields accepted when updating the current user's profile."""

    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        return _clean_name_field(v)


# ---------------------------------------------------------------------------
# Group & permission schemas
# ---------------------------------------------------------------------------


class GroupBase(BaseModel):
    """Shared group fields."""

    name: str
    description: Optional[str] = None


class GroupCreate(GroupBase):
    """Fields for creating a new group."""


class SearchSettings(BaseModel):
    """Per-group search/content setting overrides (partial — only set keys override)."""

    denseWeight: Optional[float] = None
    rerank: Optional[bool] = None
    recencyBoost: Optional[bool] = None
    recencyWeight: Optional[float] = None
    recencyScaleDays: Optional[int] = None
    sectionTypes: Optional[list[str]] = None
    keywordBoostShortQueries: Optional[bool] = None
    minChunkSize: Optional[int] = None
    semanticHighlighting: Optional[bool] = None
    autoMinScore: Optional[bool] = None
    deduplicate: Optional[bool] = None
    fieldBoost: Optional[bool] = None
    fieldBoostFields: Optional[dict[str, float]] = None
    greetingMessage: Optional[str] = None


class GroupUpdate(BaseModel):
    """Fields for updating an existing group."""

    name: Optional[str] = None
    description: Optional[str] = None
    search_settings: Optional[dict] = None
    summary_prompt: Optional[str] = None


class GroupRead(GroupBase):
    """Group representation returned by read endpoints."""

    id: uuid.UUID
    is_default: bool
    created_at: datetime
    datasource_keys: list[str] = []
    member_count: int = 0
    search_settings: Optional[dict] = None
    summary_prompt: Optional[str] = None

    model_config = {"from_attributes": True}


class GroupMemberAdd(BaseModel):
    """Payload for adding a user to a group."""

    user_id: uuid.UUID


class GroupDatasourceSet(BaseModel):
    """Payload for setting the datasource keys a group can access."""

    datasource_keys: list[str]


# ---------------------------------------------------------------------------
# Rating & activity schemas
# ---------------------------------------------------------------------------

VALID_RATING_TYPES = {
    "search_result",
    "ai_summary",
    "doc_summary",
    "taxonomy",
    "heatmap",
    "chat",
    "assistant-basic",
    "assistant-deep-research",
    # Free-form page feedback submitted via the floating feedback button.
    # Score is unused for this type; clients submit a sentinel value (3).
    "page_feedback",
}


class RatingCreate(BaseModel):
    """Payload for creating or updating a rating."""

    rating_type: str
    reference_id: str = Field(..., max_length=255)
    item_id: Optional[str] = Field(None, max_length=255)
    score: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=2000)
    context: Optional[dict] = None
    url: Optional[str] = Field(None, max_length=2000)

    @field_validator("rating_type")
    @classmethod
    def validate_rating_type(cls, v: str) -> str:
        if v not in VALID_RATING_TYPES:
            raise ValueError(
                f"rating_type must be one of: {', '.join(sorted(VALID_RATING_TYPES))}"
            )
        return v

    @field_validator("context")
    @classmethod
    def validate_context(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_jsonb(v)


# ---------------------------------------------------------------------------
# Admin response (triage) statuses
# ---------------------------------------------------------------------------
# Stored as a plain VARCHAR(32) in the DB and validated here so new values
# can be added without a migration. Order matters: the frontend uses the
# first entry as the default selection for unfilled responses.
VALID_RESPONSE_STATUSES = (
    "open",
    "acknowledged",
    "info_needed",
    "resolved",
    "wontfix",
)


class RatingRead(BaseModel):
    """Rating representation returned by read endpoints."""

    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    user_email: Optional[str] = None
    user_display_name: Optional[str] = None
    rating_type: str
    reference_id: str
    item_id: Optional[str] = None
    score: int
    comment: Optional[str] = None
    context: Optional[dict] = None
    url: Optional[str] = None
    response_status: Optional[str] = None
    response_notes: Optional[str] = None
    responded_by_user_id: Optional[uuid.UUID] = None
    responded_by_email: Optional[str] = None
    responded_by_display_name: Optional[str] = None
    responded_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RatingResponseUpdate(BaseModel):
    """Payload for the admin response (triage) endpoint.

    Both fields are optional so callers can update status alone, notes
    alone, or both. Passing ``None`` for ``response_status`` clears the
    status (and audit fields).
    """

    response_status: Optional[str] = Field(None, max_length=32)
    response_notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("response_status")
    @classmethod
    def validate_response_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in VALID_RESPONSE_STATUSES:
            raise ValueError(
                "response_status must be one of: " + ", ".join(VALID_RESPONSE_STATUSES)
            )
        return v


class _TokenUsageFields(BaseModel):
    """Optional LLM usage and cost fields shared by activity schemas.

    Defined once and mixed into the create/update/read schemas so the
    validation bounds stay consistent across endpoints.
    """

    llm_model: Optional[str] = Field(None, max_length=128)
    prompt_tokens: Optional[int] = Field(None, ge=0, le=10_000_000)
    completion_tokens: Optional[int] = Field(None, ge=0, le=10_000_000)
    cost_usd: Optional[Decimal] = Field(None, ge=0, le=1000)


class ActivityCreate(_TokenUsageFields):
    """Payload for logging a search activity."""

    search_id: str = Field(..., max_length=100)
    query: str = Field(..., max_length=5000)
    filters: Optional[dict] = None
    search_results: Optional[list] = None
    ai_summary: Optional[str] = Field(None, max_length=100_000)
    url: Optional[str] = Field(None, max_length=2000)
    session_id: Optional[str] = Field(None, max_length=64)

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_jsonb(v)

    @field_validator("search_results")
    @classmethod
    def validate_search_results(cls, v: Optional[list]) -> Optional[list]:
        return _validate_jsonb(v)


class ActivitySummaryUpdate(_TokenUsageFields):
    """Payload for updating an existing activity record.

    All fields optional: send ai_summary to update the summary text,
    summary_duration_ms to record how long the summary took,
    drilldown_tree to capture the AI Summary Tree structure.
    """

    ai_summary: Optional[str] = Field(None, max_length=100_000)
    summary_duration_ms: Optional[float] = Field(None, ge=0, le=600_000)
    drilldown_tree: Optional[dict] = None

    @field_validator("drilldown_tree")
    @classmethod
    def validate_drilldown_tree(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_jsonb(v)


class ActivitySummaryUpdateAnonymous(_TokenUsageFields):
    """Payload for updating an activity record (authenticated or anonymous)."""

    ai_summary: Optional[str] = Field(None, max_length=100_000)
    summary_duration_ms: Optional[float] = Field(None, ge=0, le=600_000)
    drilldown_tree: Optional[dict] = None
    session_id: Optional[str] = Field(None, max_length=64)

    @field_validator("drilldown_tree")
    @classmethod
    def validate_drilldown_tree(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_jsonb(v)


class ActivityRead(_TokenUsageFields):
    """Activity representation returned by admin endpoints."""

    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    session_id: Optional[str] = None
    user_email: Optional[str] = None
    user_display_name: Optional[str] = None
    search_id: uuid.UUID
    query: str
    filters: Optional[dict] = None
    search_results: Optional[Any] = None
    ai_summary: Optional[str] = None
    url: Optional[str] = None
    has_ratings: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Saved research schemas
# ---------------------------------------------------------------------------

_MAX_RESEARCH_JSONB_SIZE = 10_000_000  # 10 MB limit for full research trees
_MAX_RESEARCH_JSONB_DEPTH = (
    20  # Research trees are deeply nested (nodes → results → headings)
)


def _validate_research_jsonb(v: Any) -> Any:
    """Validate a research JSONB payload (larger limit than standard)."""
    if v is None:
        return v
    _check_jsonb_depth(v, max_depth=_MAX_RESEARCH_JSONB_DEPTH)
    import json

    if len(json.dumps(v, default=str)) > _MAX_RESEARCH_JSONB_SIZE:
        raise ValueError(
            f"Research tree exceeds maximum size of "
            f"{_MAX_RESEARCH_JSONB_SIZE} characters"
        )
    return v


class SavedResearchCreate(BaseModel):
    """Payload for saving a research tree."""

    title: str = Field(..., max_length=500)
    query: str = Field(..., max_length=5000)
    filters: Optional[dict] = None
    data_source: Optional[str] = Field(None, max_length=255)
    drilldown_tree: dict

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_jsonb(v)

    @field_validator("drilldown_tree")
    @classmethod
    def validate_tree(cls, v: dict) -> dict:
        return _validate_research_jsonb(v)


class SavedResearchUpdate(BaseModel):
    """Payload for updating saved research."""

    title: Optional[str] = Field(None, max_length=500)
    drilldown_tree: Optional[dict] = None
    filters: Optional[dict] = None

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_jsonb(v)

    @field_validator("drilldown_tree")
    @classmethod
    def validate_tree(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_research_jsonb(v)


class SavedResearchRead(BaseModel):
    """Full saved research returned by read endpoints."""

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    query: str
    filters: Optional[dict] = None
    data_source: Optional[str] = None
    drilldown_tree: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SavedResearchListItem(BaseModel):
    """Compact saved research for list/table views (omits large tree)."""

    id: uuid.UUID
    title: str
    query: str
    data_source: Optional[str] = None
    node_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Brief Central schemas (briefs, templates, voice profiles, shares)
# ---------------------------------------------------------------------------


class VoiceProfileCreate(BaseModel):
    """Payload for creating a voice & tone profile."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    instructions: str = Field(..., min_length=1, max_length=10_000)


class VoiceProfileUpdate(BaseModel):
    """Payload for updating a voice & tone profile."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    instructions: Optional[str] = Field(None, min_length=1, max_length=10_000)


class VoiceProfileRead(BaseModel):
    """Voice & tone profile returned by read endpoints."""

    id: uuid.UUID
    name: str
    description: Optional[str] = None
    instructions: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BriefTemplateHeading(BaseModel):
    """One heading in a brief template."""

    title: str = Field(..., min_length=1, max_length=500)
    sub: bool = False
    text: Optional[str] = Field(None, max_length=100_000)


class BriefTemplateCreate(BaseModel):
    """Payload for creating a brief template."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    headings: List[BriefTemplateHeading] = Field(..., min_length=1, max_length=100)
    with_text: bool = False


class BriefTemplateUpdate(BaseModel):
    """Payload for updating a brief template."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    headings: Optional[List[BriefTemplateHeading]] = Field(
        None, min_length=1, max_length=100
    )
    with_text: Optional[bool] = None


class BriefTemplateRead(BaseModel):
    """Brief template returned by read endpoints."""

    id: uuid.UUID
    name: str
    description: Optional[str] = None
    headings: List[BriefTemplateHeading]
    with_text: bool
    use_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BriefCreate(BaseModel):
    """Payload for saving a brief."""

    title: str = Field(..., min_length=1, max_length=500)
    query: Optional[str] = Field(None, max_length=5000)
    data_source: Optional[str] = Field(None, max_length=255)
    voice_profile_id: Optional[uuid.UUID] = None
    content: dict

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: dict) -> dict:
        return _validate_research_jsonb(v)


class BriefUpdate(BaseModel):
    """Payload for updating a brief."""

    title: Optional[str] = Field(None, min_length=1, max_length=500)
    query: Optional[str] = Field(None, max_length=5000)
    voice_profile_id: Optional[uuid.UUID] = None
    content: Optional[dict] = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_research_jsonb(v)


class BriefShareTarget(BaseModel):
    """One person or group a brief is shared with."""

    id: uuid.UUID
    name: str
    kind: str  # the user's email, or "Group · N members"
    is_group: bool


class BriefCommentCreate(BaseModel):
    """A new comment, or a reply when ``parent_id`` is set."""

    body: str = Field(min_length=1, max_length=5000)
    # Anchor: which section, and the highlighted text with a little context.
    section_id: Optional[str] = Field(default=None, max_length=64)
    quote: Optional[str] = Field(default=None, max_length=2000)
    quote_prefix: Optional[str] = Field(default=None, max_length=500)
    quote_suffix: Optional[str] = Field(default=None, max_length=500)
    parent_id: Optional[uuid.UUID] = None


class BriefCommentUpdate(BaseModel):
    """Edit a comment's text, or resolve/reopen its thread."""

    body: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    resolved: Optional[bool] = None


class BriefCommentRead(BaseModel):
    """A comment as shown in the brief's comment rail."""

    id: uuid.UUID
    brief_id: uuid.UUID
    parent_id: Optional[uuid.UUID] = None
    section_id: Optional[str] = None
    quote: Optional[str] = None
    quote_prefix: Optional[str] = None
    quote_suffix: Optional[str] = None
    body: str
    resolved: bool
    author_name: str
    author_email: str
    # True when the signed-in user wrote it (drives Edit/Delete affordances).
    is_mine: bool
    created_at: datetime
    updated_at: datetime


class BriefRead(BaseModel):
    """Full brief returned by read endpoints."""

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    query: Optional[str] = None
    data_source: Optional[str] = None
    voice_profile_id: Optional[uuid.UUID] = None
    content: dict
    owner_name: Optional[str] = None
    can_edit: bool = True
    shared_with: List[BriefShareTarget] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BriefListItem(BaseModel):
    """Compact brief for card/list views (omits full content)."""

    id: uuid.UUID
    title: str
    query: Optional[str] = None
    data_source: Optional[str] = None
    voice_profile_id: Optional[uuid.UUID] = None
    section_count: int = 0
    source_count: int = 0
    owner_name: Optional[str] = None
    share_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BriefShareCreate(BaseModel):
    """Add a viewer (user by email, or group by name) to a brief."""

    target: str = Field(..., min_length=1, max_length=320)


# ---------------------------------------------------------------------------
# API key schemas
# ---------------------------------------------------------------------------


class ApiKeyCreate(BaseModel):
    """Payload for generating a new API key."""

    label: str = Field("API Key", min_length=1, max_length=255)


class ApiKeyRead(BaseModel):
    """API key representation — includes the stored plaintext key when available."""

    id: uuid.UUID
    label: str
    key_prefix: str
    key_value: Optional[str] = None
    is_active: bool
    created_at: datetime
    created_by_email: Optional[str] = None
    last_used_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyRead):
    """Returned at creation time — includes the full plaintext key."""

    key: str


# ----- Research Assistant Schemas -----


class AssistantModelConfig(BaseModel):
    """LLM configuration for the research assistant."""

    model: str
    max_tokens: int = 2000
    temperature: float = 0.0
    chunk_overlap: int = 800
    chunk_tokens_ratio: float = 0.5


class AssistantSearchSettings(BaseModel):
    """Search settings passed from frontend for assistant searches."""

    dense_weight: Optional[float] = None
    recency_boost: Optional[bool] = None
    recency_weight: Optional[float] = None
    recency_scale_days: Optional[int] = None
    section_types: Optional[list[str]] = None
    keyword_boost_short_queries: Optional[bool] = None
    min_chunk_size: Optional[int] = None
    field_boost_enabled: Optional[bool] = None
    field_boost_fields: Optional[dict[str, float]] = None


class AssistantChatRequest(BaseModel):
    """Request payload for assistant chat streaming endpoint."""

    query: str = Field(..., max_length=5000)
    thread_id: Optional[str] = None
    data_source: Optional[str] = Field(None, max_length=255)
    assistant_model_config: Optional[AssistantModelConfig] = None
    reranker_model: Optional[str] = None
    search_settings: Optional[AssistantSearchSettings] = None
    deep_research: bool = False
    conversation_history: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "Prior conversation messages for unauthenticated users. Each "
            "entry has 'role' and 'content'; assistant entries may also "
            "carry 'sources' so citation numbers stay resolvable across "
            "follow-up turns."
        ),
    )
    # Activity row (search_id) this turn's token usage is recorded onto,
    # server-side, when the stream finishes — plus the anonymous session id
    # for owner scoping. Brief sections pass their brief's stable activity
    # id here so all section research accumulates onto one row, and set
    # usage_context='brief' so a newly created row is typed 'brief' rather
    # than 'assistant-deep-research'.
    activity_id: Optional[str] = Field(None, max_length=100)
    session_id: Optional[str] = Field(None, max_length=64)
    usage_context: Optional[str] = Field(None, max_length=32)


class ThreadRenameRequest(BaseModel):
    """Request payload for renaming a conversation thread."""

    title: str = Field(..., min_length=1, max_length=500)


class ConversationMessageRead(BaseModel):
    """Single message in a conversation thread."""

    id: uuid.UUID
    thread_id: uuid.UUID
    role: str
    content: str
    sources: Optional[dict] = None
    agent_state: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationThreadRead(BaseModel):
    """Full conversation thread with messages."""

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    data_source: Optional[str] = None
    metadata_json: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageRead] = []

    model_config = {"from_attributes": True}


class ConversationThreadListItem(BaseModel):
    """Compact thread for list views (omits messages)."""

    id: uuid.UUID
    title: str
    data_source: Optional[str] = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
