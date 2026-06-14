"""Pydantic request/response schemas for the admin evaluation harness.

Superuser-only. Mirrors the ``test_*`` ORM models. Assertions and
input/config are kept as flexible dict/list payloads (validated by the
evaluators/runner) so new assertion types do not require a schema change.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


class TestDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    capability: str = Field(description="search | ai_summary")
    data_source: str = Field(min_length=1, max_length=255)


class TestDatasetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    data_source: Optional[str] = Field(default=None, min_length=1, max_length=255)


class TestDatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str] = None
    capability: str
    data_source: str
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    # Aggregated, list-view-only fields (populated by the route, not the ORM).
    num_cases: Optional[int] = None
    last_run_at: Optional[datetime] = None
    last_pass_rate: Optional[float] = None


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestCaseCreate(BaseModel):
    input: Dict[str, Any]
    expectations: List[Dict[str, Any]] = Field(default_factory=list)
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class TestCaseUpdate(BaseModel):
    input: Optional[Dict[str, Any]] = None
    expectations: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class TestCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    input: Dict[str, Any]
    expectations: List[Dict[str, Any]]
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Experiments + results
# ---------------------------------------------------------------------------


class TestExperimentCreate(BaseModel):
    dataset_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    config: Optional[Dict[str, Any]] = None


class TestResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    experiment_id: uuid.UUID
    test_case_id: uuid.UUID
    status: str
    score: Optional[float] = None
    actual_output: Optional[Dict[str, Any]] = None
    assertion_results: Optional[List[Dict[str, Any]]] = None
    latency_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime


class TestExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    status: str
    config: Optional[Dict[str, Any]] = None
    summary_stats: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime


class TestExperimentDetail(TestExperimentRead):
    results: List[TestResultRead] = Field(default_factory=list)
