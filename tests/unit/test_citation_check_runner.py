"""Unit tests for the brief citation check runner (judge and DB faked)."""

import json
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook

from ui.backend.services import citation_check_runner as runner
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.services.citation_fidelity import CitedPassage

pytestmark = pytest.mark.unit

EXCERPT = "Dropout fell from 12 to 7 percent in schools receiving meals."
SOURCE = {
    "index": 1,
    "title": "Kenya evaluation",
    "page": 4,
    "docId": "d1",
    "chunkId": "c1",
    "text": EXCERPT,
}
# A brief in citation format 2, as the API stores it: the check reads the
# renumbered text, where the agent's dangling [2] is kept visible as [?2].
BRIEF = convert_legacy(
    {
        "sections": [
            {
                "title": "Dropout",
                "status": "done",
                "content": "Dropout fell in fed schools [1]. Boys were unaffected [2].",
                "sources": [SOURCE],
            },
            {"title": "Draft", "status": "pending", "content": "", "sources": []},
        ]
    }
)[0]


def _passage(**kwargs) -> CitedPassage:
    base = dict(
        section_title="Dropout",
        passage="Dropout fell [1].",
        citation_indices=[1],
        sources=[SOURCE],
    )
    return CitedPassage(**{**base, **kwargs})


GOOD_REPLY = (
    '{"verdict": "supported", "confidence": 0.9, '
    '"supporting_quotes": [{"citation": 1, "quote": "Dropout fell from 12 to 7 percent"}], '
    '"problems": [], "explanation": "Matches."}'
)


class TestPassagesAndPrompts:
    def test_brief_passages_when_section_pending_then_only_done_sections(self):
        passages = runner.brief_passages(BRIEF)
        assert [p.passage for p in passages] == [
            "Dropout fell in fed schools [1].",
            "Boys were unaffected [?2].",
        ]
        assert passages[1].missing_indices == [2]
        assert runner.count_cited_passages(BRIEF) == 2


class TestPassageRecord:
    def test_record_when_reply_valid_then_verdict_and_quote_verified(self):
        judgement = json.loads(GOOD_REPLY)
        record = runner.passage_record(
            1, _passage(), judgement, {"prompt_tokens": 10, "completion_tokens": 5}
        )
        assert record["verdict"] == "supported" and record["flagged"] is False
        assert record["supporting_quotes"][0]["status"] == "verbatim"
        assert (
            record["quotes_verified"] == "1/1"
            and record["quote_not_in_source"] is False
        )
        assert record["sources"][0]["excerpt"] == EXCERPT
        assert record["prompt_tokens"] == 10 and record["error_message"] is None

    def test_record_when_quote_invented_then_flagged_not_in_source(self):
        reply = GOOD_REPLY.replace(
            "Dropout fell from 12 to 7 percent", "enrolment doubled overnight"
        )
        record = runner.passage_record(1, _passage(), json.loads(reply))
        assert record["quote_not_in_source"] is True
        assert record["supporting_quotes"][0]["status"] == "missing"


class TestSummary:
    def _rows(self):
        return [
            {
                "brief_section": "A",
                "verdict": "supported",
                "flagged": False,
                "quote_not_in_source": False,
                "prompt_tokens": 10,
                "completion_tokens": 2,
            },
            {
                "brief_section": "A",
                "verdict": "unsupported",
                "flagged": True,
                "quote_not_in_source": True,
                "prompt_tokens": 10,
                "completion_tokens": 2,
            },
            {
                "brief_section": "B",
                "verdict": "partially_supported",
                "flagged": True,
                "quote_not_in_source": False,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "error_message": "JUDGE ERROR",
            },
        ]

    def test_summarise_when_rows_then_counts_sections_and_tokens(self, monkeypatch):
        monkeypatch.setattr(
            "ui.backend.utils.llm_costs.compute_cost", lambda m, p, c: 0.0123
        )
        stats = runner.summarise(self._rows(), 1500, "judge-x")
        assert stats["total"] == 3 and stats["flagged"] == 2
        assert stats["verdicts"] == {
            "supported": 1,
            "partially_supported": 1,
            "unsupported": 1,
            "cannot_assess": 0,
        }
        assert stats["flagged_share"] == 0.67
        assert stats["quote_not_in_source"] == 1 and stats["not_judged"] == 1
        assert [s["brief_section"] for s in stats["by_section"]] == ["A", "B"]
        assert stats["by_section"][0]["flagged_share"] == 0.5
        assert stats["total_tokens"] == 24 and stats["cost_usd"] == 0.0123

    def test_build_workbook_when_passages_then_three_sheets_flagged_by_severity(self):
        passages = [
            {
                "passage_id": 1,
                "brief_section": "A",
                "passage": "p1",
                "verdict": "partially_supported",
                "flagged": True,
                "confidence": 0.9,
                "problems": ["x"],
                "supporting_quotes": [{"citation": 1, "quote": "q", "status": "near"}],
            },
            {
                "passage_id": 2,
                "brief_section": "A",
                "passage": "p2",
                "verdict": "unsupported",
                "flagged": True,
                "confidence": 0.5,
                "problems": [],
                "supporting_quotes": [],
            },
            {
                "passage_id": 3,
                "brief_section": "A",
                "passage": "p3",
                "verdict": "supported",
                "flagged": False,
                "confidence": 1.0,
                "problems": [],
                "supporting_quotes": [],
            },
        ]
        book = load_workbook(
            BytesIO(
                runner.build_review_workbook(
                    passages, [{"brief_section": "A", "total": 3}]
                )
            )
        )
        assert book.sheetnames == ["Flagged", "All judgements", "Summary"]
        flagged = list(book["Flagged"].iter_rows(values_only=True))
        assert flagged[0][0] == "passage_id"
        assert [r[0] for r in flagged[1:]] == [2, 1]
        all_rows = list(book["All judgements"].iter_rows(values_only=True))
        assert len(all_rows) == 4 and "[1] q (near)" in all_rows[1]


class FakeSession:
    """Just enough AsyncSession for the runner: get/add/commit/execute."""

    def __init__(self, check, brief, versions=()):
        self.rows = {("check", check.id): check, ("brief", brief.id): brief}
        self.versions = list(versions)
        self.added = []
        self.commits = 0

    async def get(self, model, key):
        kind = "brief" if model.__name__ == "Brief" else "check"
        return self.rows.get((kind, key))

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def execute(self, statement):
        if "FROM brief_versions" in str(statement):
            rows = sorted(self.versions, key=lambda v: -v.number)
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(first=lambda: rows[0] if rows else None)
            )
        return SimpleNamespace(rowcount=0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _check_and_brief():
    brief = SimpleNamespace(id=uuid.uuid4(), content=BRIEF)
    check = SimpleNamespace(
        id=uuid.uuid4(),
        brief_id=brief.id,
        brief_title="B",
        data_source="wfp",
        created_by_user_id=uuid.uuid4(),
        judge_model="judge-x",
        brief_version_id=None,
        brief_version_number=None,
        status="pending",
        summary_stats=None,
        started_at=None,
        finished_at=None,
    )
    return check, brief


class TestRunCheck:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["completed", "failed", "running"])
    async def test_retry_leaves_existing_check_alone(self, status):
        check, brief = _check_and_brief()
        check.status = status
        session = FakeSession(check, brief)
        await runner.run_check(check.id, session_factory=lambda: session)
        assert check.status == status and session.commits == 0

    @pytest.mark.asyncio
    async def test_pending_legacy_check_explains_how_to_start_a_new_check(self):
        check, brief = _check_and_brief()
        check.check_kind = "citation"
        session = FakeSession(check, brief)
        await runner.run_check(check.id, session_factory=lambda: session)
        assert (
            check.status == "failed" and "Start a new" in check.summary_stats["error"]
        )

    @pytest.mark.asyncio
    async def test_full_check_uses_shared_grader_and_reports_failure(self, monkeypatch):
        check, brief = _check_and_brief()
        check.check_kind = "full"
        session = FakeSession(check, brief)
        grade = AsyncMock(side_effect=RuntimeError("internal detail"))
        monkeypatch.setattr(
            "ui.backend.services.saved_brief_check_runner.run_full_check", grade
        )
        await runner.run_check(check.id, session_factory=lambda: session)
        grade.assert_awaited_once_with(session, check)
        assert check.summary_stats == {"error": "Check failed"}

    @pytest.mark.asyncio
    async def test_usage_is_recorded_for_the_same_check(self, monkeypatch):
        record = AsyncMock()
        monkeypatch.setattr(
            "ui.backend.services.usage_recorder.record_llm_usage", record
        )
        check, _ = _check_and_brief()
        check.summary_stats = {"prompt_tokens": 12, "total": 2}
        await runner._record_check_usage(check)
        assert record.await_args.kwargs["search_id"] == check.id
        assert record.await_args.kwargs["usage"]["prompt_tokens"] == 12


class TestResolveJudgeModel:
    def test_resolve_when_combo_has_summary_model_then_used(self, monkeypatch):
        monkeypatch.setattr(
            "ui.backend.services.test_runner._resolve_combo",
            lambda name: {"summary_model": "combo-model"} if name == "X" else {},
        )
        monkeypatch.setattr(
            "ui.backend.services.test_runner._default_summary_model", lambda: "default"
        )
        monkeypatch.setattr("ui.backend.services.llm_choice.default_combo", lambda: {})
        assert runner.resolve_judge_model("X") == "combo-model"
        assert runner.resolve_judge_model(None) == "default"
