"""Pydantic schemas for user authentication and permissions."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi_users import schemas
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# fastapi-users schemas (registration, login, profile)
# ---------------------------------------------------------------------------


def _clean_display_name(v: Optional[str]) -> Optional[str]:
    """Strip whitespace from display names; treat blank as None."""
    if v is not None:
        v = v.strip()
        if len(v) == 0:
            return None
    return v


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Public user representation returned by read endpoints."""

    display_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserCreate(schemas.BaseUserCreate):
    """Fields accepted when registering a new user."""

    display_name: Optional[str] = Field(None, max_length=255)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        return _clean_display_name(v)


class UserUpdate(schemas.BaseUserUpdate):
    """Fields accepted when updating the current user's profile."""

    display_name: Optional[str] = Field(None, max_length=255)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        return _clean_display_name(v)


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


class GroupUpdate(BaseModel):
    """Fields for updating an existing group."""

    name: Optional[str] = None
    description: Optional[str] = None
    search_settings: Optional[dict] = None


class GroupRead(GroupBase):
    """Group representation returned by read endpoints."""

    id: uuid.UUID
    is_default: bool
    created_at: datetime
    datasource_keys: list[str] = []
    member_count: int = 0
    search_settings: Optional[dict] = None

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
}


class RatingCreate(BaseModel):
    """Payload for creating or updating a rating."""

    rating_type: str
    reference_id: str
    item_id: Optional[str] = None
    score: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=2000)
    context: Optional[dict] = None
    url: Optional[str] = None

    @field_validator("rating_type")
    @classmethod
    def validate_rating_type(cls, v: str) -> str:
        if v not in VALID_RATING_TYPES:
            raise ValueError(
                f"rating_type must be one of: {', '.join(sorted(VALID_RATING_TYPES))}"
            )
        return v


class RatingRead(BaseModel):
    """Rating representation returned by read endpoints."""

    id: uuid.UUID
    user_id: uuid.UUID
    user_email: Optional[str] = None
    user_display_name: Optional[str] = None
    rating_type: str
    reference_id: str
    item_id: Optional[str] = None
    score: int
    comment: Optional[str] = None
    context: Optional[dict] = None
    url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActivityCreate(BaseModel):
    """Payload for logging a search activity."""

    search_id: str
    query: str
    filters: Optional[dict] = None
    search_results: Optional[list] = None
    ai_summary: Optional[str] = None
    url: Optional[str] = None


class ActivitySummaryUpdate(BaseModel):
    """Payload for updating an existing activity record.

    All fields optional: send ai_summary to update the summary text,
    summary_duration_ms to record how long the summary took,
    drilldown_tree to capture the AI Summary Tree structure.
    """

    ai_summary: Optional[str] = None
    summary_duration_ms: Optional[float] = None
    drilldown_tree: Optional[dict] = None


class ActivityRead(BaseModel):
    """Activity representation returned by admin endpoints."""

    id: uuid.UUID
    user_id: uuid.UUID
    user_email: Optional[str] = None
    user_display_name: Optional[str] = None
    search_id: uuid.UUID
    query: str
    filters: Optional[dict] = None
    search_results: Optional[list] = None
    ai_summary: Optional[str] = None
    url: Optional[str] = None
    has_ratings: bool
    created_at: datetime

    model_config = {"from_attributes": True}
