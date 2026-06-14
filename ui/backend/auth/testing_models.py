"""SQLAlchemy ORM models for the admin Search & AI-Summary evaluation harness.

Internal, superuser-only evaluation/regression tooling. Four tables:

- ``test_datasets``    — a reusable set of test cases for one capability.
- ``test_cases``       — a single input + its expected assertions.
- ``test_experiments`` — one run of a dataset against the live capability.
- ``test_results``     — per-case outcome (status, score, raw output, asserts).

Shares the single declarative ``Base`` from :mod:`ui.backend.auth.models` so
the tables register on the same metadata. Schema changes go through Alembic
(see ``alembic/versions/0028_add_testing_harness.py``); these models are the
runtime ORM mapping only.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ui.backend.auth.models import Base

# Capability identifiers (kept in sync with the evaluator/runner dispatch).
CAPABILITY_SEARCH = "search"
CAPABILITY_AI_SUMMARY = "ai_summary"
VALID_CAPABILITIES = {CAPABILITY_SEARCH, CAPABILITY_AI_SUMMARY}

# Experiment lifecycle states.
EXPERIMENT_PENDING = "pending"
EXPERIMENT_RUNNING = "running"
EXPERIMENT_COMPLETED = "completed"
EXPERIMENT_FAILED = "failed"

# Per-case result states.
RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_ERROR = "error"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestDataset(Base):
    """A reusable, named collection of test cases for one capability."""

    __tablename__ = "test_datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    data_source: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    cases: Mapped[list["TestCase"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class TestCase(Base):
    """A single test case: input parameters and the assertions to evaluate."""

    __tablename__ = "test_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # input: {"query": str, "filters": {...}, "params": {...}}
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # expectations: [{"type": str, ...params}, ...]
    expectations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    dataset: Mapped["TestDataset"] = relationship(back_populates="cases")


class TestExperiment(Base):
    """One run of a dataset against the live capability."""

    __tablename__ = "test_experiments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EXPERIMENT_PENDING
    )
    # config: model/params used for the run (e.g. summary_model, rerank, limit)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # summary_stats: {passed, failed, errored, total, pass_rate, mean_score,
    #                 duration_ms}
    summary_stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    results: Mapped[list["TestResult"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class TestResult(Base):
    """Outcome of evaluating one test case within an experiment."""

    __tablename__ = "test_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # actual_output: full raw capability output, never truncated
    actual_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # assertion_results: [{type, passed, message, score?}, ...]
    assertion_results: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    experiment: Mapped["TestExperiment"] = relationship(back_populates="results")
