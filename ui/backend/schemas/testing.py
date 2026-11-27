"""Pydantic request/response schemas for the admin evaluation harness.

Superuser-only. Mirrors the ``test_*`` ORM models. Assertions and
input/config are kept as flexible dict/list payloads (validated by the
evaluators/runner) so new assertion types do not require a schema change.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ui.backend.auth.schemas import (
    BRIEF_HEADING_MAX_CHARS,
    BRIEF_MAX_SECTIONS,
    BRIEF_PROMPT_MAX_CHARS,
    BRIEF_TOPIC_MAX_CHARS,
    TARGET_WORDS_MAX,
    TARGET_WORDS_MIN,
    VOICE_INSTRUCTIONS_MAX_CHARS,
    BriefOutlineSection,
)
from ui.backend.services.brief_experiment_claims import (
    brief_claim_evidence,
    link_assessment_claims,
)
from ui.backend.services.brief_experiment_overlap import link_saved_repetitions

# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


class BriefCaseVoice(BaseModel):
    """The selected profile as it was saved in the evaluation case."""

    model_config = ConfigDict(str_strip_whitespace=True)
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    instructions: str = Field(min_length=1, max_length=VOICE_INSTRUCTIONS_MAX_CHARS)


class BriefCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=BRIEF_TOPIC_MAX_CHARS)
    heading: str = Field(min_length=1, max_length=BRIEF_HEADING_MAX_CHARS)
    guidance: str = Field("", max_length=BRIEF_PROMPT_MAX_CHARS)
    voice: str = Field("", max_length=VOICE_INSTRUCTIONS_MAX_CHARS)
    voice_profile: BriefCaseVoice | None = None
    target_words: int | None = Field(None, ge=TARGET_WORDS_MIN, le=TARGET_WORDS_MAX)
    siblings: list[BriefOutlineSection] = Field(
        default_factory=list, max_length=BRIEF_MAX_SECTIONS - 1
    )
    children: list[BriefOutlineSection] = Field(
        default_factory=list, max_length=BRIEF_MAX_SECTIONS - 1
    )
    reference_standard: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outline_size(self):
        if len(self.siblings) + len(self.children) >= BRIEF_MAX_SECTIONS:
            raise ValueError("The brief outline has too many sections.")
        return self


class TestDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    capability: str = Field(description="search | ai_summary | brief")
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


# Assertion matrix (flexible JSON blob), shape:
#   {
#     "columns": [ {"type": ..., <params>}, ... ],   # ordered assertion columns
#     "cases":   { "<case_id>": {"active": bool, "cols": [bool, ...]}, ... },
#   }
# A case runs only when its state is active; an assertion column applies to a
# case only when its aligned ``cols[i]`` flag is true.
CaseExpectations = Dict[str, Any]


class TestCaseCreate(BaseModel):
    input: Dict[str, Any]
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class TestCaseUpdate(BaseModel):
    input: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class TestCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    input: Dict[str, Any]
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
    case_expectations: Optional[CaseExpectations] = None


class TestExperimentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    config: Optional[Dict[str, Any]] = None
    case_expectations: Optional[CaseExpectations] = None


class TestResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    experiment_id: uuid.UUID
    run_id: Optional[uuid.UUID] = None
    test_case_id: uuid.UUID | None
    status: str
    score: Optional[float] = None
    actual_output: Optional[Dict[str, Any]] = None
    brief_evidence: Optional[Dict[str, Any]] = None
    assertion_results: Optional[List[Dict[str, Any]]] = None
    latency_ms: Optional[int] = None
    error_message: Optional[str] = None
    # Combined LLM usage for the case (summary + judge calls).
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    created_at: datetime

    @model_validator(mode="after")
    def attach_saved_brief_evidence(self):
        self.brief_evidence = brief_claim_evidence(self.actual_output)
        if self.brief_evidence and self.assertion_results:
            self.assertion_results = link_assessment_claims(
                self.assertion_results, self.brief_evidence
            )
        if (
            self.actual_output
            and self.actual_output.get("capability") == "brief"
            and self.assertion_results
        ):
            self.assertion_results = link_saved_repetitions(
                self.assertion_results, self.actual_output
            )
        return self


class TestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    experiment_id: uuid.UUID
    run_number: int
    status: str
    summary_stats: Optional[Dict[str, Any]] = None
    # Snapshot of the models, group and settings the run executed with.
    config: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    # The user the run (and its token usage) is attributed to — whoever
    # clicked Run, falling back to the experiment's creator.
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    results: List[TestResultRead] = Field(default_factory=list)


class TestExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    status: str
    config: Optional[Dict[str, Any]] = None
    case_expectations: Optional[CaseExpectations] = None
    summary_stats: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime


class TestExperimentDetail(TestExperimentRead):
    runs: List[TestRunRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Brief citation check
# ---------------------------------------------------------------------------


# How the current user can see a brief: their own, shared with them, or
# (admins only) another user's brief that was not shared with them.
BriefAccess = Literal["own", "shared", "other"]
BRIEF_ACCESS_OWN: BriefAccess = "own"
BRIEF_ACCESS_SHARED: BriefAccess = "shared"
BRIEF_ACCESS_OTHER: BriefAccess = "other"


class BriefCheckCandidate(BaseModel):
    """A brief the current user may check: their own, one shared with them
    or, for an admin, any other user's."""

    id: uuid.UUID
    title: str
    data_source: Optional[str] = None
    updated_at: datetime
    owner_name: str
    access: BriefAccess
    researched_sections: int
    cited_passages: int
    last_check: Optional["BriefCitationCheckRead"] = None


class BriefCitationCheckCreate(BaseModel):
    brief_id: uuid.UUID
    model_combo: Optional[str] = Field(default=None, max_length=255)


class BriefCitationCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brief_id: uuid.UUID
    brief_title: str
    data_source: Optional[str] = None
    created_by_user_id: Optional[uuid.UUID] = None
    judge_model: Optional[str] = None
    model_combo: Optional[str] = None
    # The brief version the check judged (None on checks made before
    # versions were linked) and whether the brief has a newer version since
    # (None when no version was recorded). The routes set ``brief_changed``.
    brief_version_number: Optional[int] = None
    brief_changed: Optional[bool] = None
    status: str
    summary_stats: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime


class BriefCitationCheckPassageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    passage_id: int
    brief_section: str
    passage: str
    citations: str
    documents: str
    sources: List[Dict[str, Any]]
    dangling_citations: str
    verdict: str
    flagged: bool
    confidence: Optional[float] = None
    problems: List[str]
    explanation: str
    supporting_quotes: List[Dict[str, Any]]
    quotes_verified: str
    quote_not_in_source: bool
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    error_message: Optional[str] = None


class BriefCitationCheckDetail(BriefCitationCheckRead):
    passages: List[BriefCitationCheckPassageRead] = Field(default_factory=list)


class BriefFactCheckMark(BaseModel):
    """One passage the Fact Checker highlights in an open brief: where it is,
    what the judge decided and why. ``passage`` is the prose as the check
    stored it (markers and markdown removed), which the browser locates in
    the rendered section."""

    passage_id: int
    section_id: Optional[str] = None
    section_title: str
    passage: str
    verdict: str
    verdict_label: str
    explanation: str
    problems: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    citations: str
    quote_not_in_source: bool


class BriefFactCheckLegendItem(BaseModel):
    """One verdict of the Fact Checker's legend: its label and how many of
    the highlighted passages carry it."""

    verdict: str
    label: str
    count: int


class BriefFactCheckSegment(BaseModel):
    """A run of an excerpt, highlighted when the judge quoted it."""

    text: str
    highlighted: bool


class BriefFactCheckEvidence(BaseModel):
    """One cited source as the judge read it: where it comes from, and its
    excerpt cut into plain and quoted runs. ``quoted`` says whether any of
    the judge's quotes was found in it."""

    citation: Optional[int] = None
    label: str
    title: str
    page: Optional[int] = None
    section: str = ""
    doc_id: Optional[str] = None
    chunk_id: Optional[str] = None
    pdf_url: Optional[str] = None
    quoted: bool
    segments: List[BriefFactCheckSegment]


class BriefFactCheckEvidenceRead(BaseModel):
    """GET /briefs/{id}/fact-check/{check_id}/passages/{passage_id}: the
    evidence behind one highlighted passage, loaded when its card opens."""

    passage_id: int
    verdict: str
    verdict_label: str
    evidence: List[BriefFactCheckEvidence]


class BriefFactCheckSection(BaseModel):
    """A section with cited passages that changed since the check judged
    the brief, so the Fact Checker does not cover it; ``note`` is shown
    above it while the highlights are on."""

    id: str
    title: str
    note: str


class BriefFactCheckRead(BaseModel):
    """What the Fact Checker button needs: the completed check that still
    covers at least one section of the brief (``None`` when there is none,
    so the button stays hidden), the version it judged and the brief's
    current version, a note on how they relate, the sections the check no
    longer covers, the legend of verdict colours with their counts, and the
    marks (every judged passage of a covered section)."""

    check: Optional[BriefCitationCheckRead] = None
    brief_version: Optional[int] = None
    current_version: Optional[int] = None
    note: str = ""
    changed_sections: List[BriefFactCheckSection] = Field(default_factory=list)
    legend: List[BriefFactCheckLegendItem] = Field(default_factory=list)
    marks: List[BriefFactCheckMark] = Field(default_factory=list)


BriefCheckCandidate.model_rebuild()
