"""Unit tests for the brief citation check runner (judge and DB faked)."""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook
from sqlalchemy import Select

from ui.backend.services import citation_check_runner as runner
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.services.citation_fidelity import CitedPassage
from ui.backend.services.job_liveness import progress_stats

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)

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
        stats = runner.summarise(
            self._rows(), 1500, "judge-x", reference_lines_skipped=5
        )
        assert stats["total"] == 3 and stats["flagged"] == 2
        assert stats["reference_lines_skipped"] == 5
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
    """Just enough AsyncSession for the runner. The runner owns its row only
    through conditional UPDATEs, so those are interpreted: the values apply
    only when the row's status is in the statement's WHERE list, and
    ``rowcount`` says whether they did. Rows added since the last commit are
    dropped by a rollback, as in SQLAlchemy."""

    def __init__(self, check, brief, checks=()):
        self.brief = brief
        self.checks = [check, *checks]
        self.added, self.pending = [], []
        self.commits = self.rollbacks = 0

    async def get(self, model, key):
        if model.__name__ == "Brief":
            return self.brief if self.brief and self.brief.id == key else None
        return next((c for c in self.checks if c.id == key), None)

    def add(self, row):
        self.pending.append(row)

    async def commit(self):
        self.commits += 1
        self.added.extend(self.pending)
        self.pending = []

    async def rollback(self):
        self.rollbacks += 1
        self.pending = []

    async def execute(self, statement):
        if isinstance(statement, Select):
            rows = list(self.checks)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))
        params = statement.compile().params
        row = next((c for c in self.checks if c.id == params.get("id_1")), None)
        if row is None or row.status not in (params.get("status_1") or []):
            return SimpleNamespace(rowcount=0)
        for key, value in params.items():
            if not re.search(r"_\d+$", key):
                setattr(row, key, value)
        return SimpleNamespace(rowcount=1)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _check_and_brief(status="pending", **over):
    brief = SimpleNamespace(id=uuid.uuid4(), content=BRIEF)
    fields = dict(
        id=uuid.uuid4(),
        brief_id=brief.id,
        brief_title="B",
        data_source="wfp",
        created_by_user_id=uuid.uuid4(),
        judge_model="judge-x",
        check_kind="full",
        brief_version_id=None,
        brief_version_number=None,
        status=status,
        summary_stats=None,
        started_at=None,
        finished_at=None,
        created_at=NOW,
    )
    return SimpleNamespace(**{**fields, **over}), brief


class TestRunCheck:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["completed", "failed", "running"])
    async def test_retry_leaves_existing_check_alone(self, status):
        """Only a pending check is run: a completed one is history, a failed
        one was cancelled (or failed as orphaned on another api copy) while
        queued, and a running one belongs to another api copy."""
        check, brief = _check_and_brief(status=status, summary_stats={"error": "x"})
        session = FakeSession(check, brief)
        await runner.run_check(check.id, session_factory=lambda: session)
        assert check.status == status and session.commits == 0
        assert check.summary_stats == {"error": "x"}

    @pytest.mark.asyncio
    async def test_pending_legacy_check_explains_how_to_start_a_new_check(self):
        check, brief = _check_and_brief(check_kind="citation")
        session = FakeSession(check, brief)
        await runner.run_check(check.id, session_factory=lambda: session)
        assert (
            check.status == "failed" and "Start a new" in check.summary_stats["error"]
        )
        assert check.finished_at is not None

    @pytest.mark.asyncio
    async def test_full_check_uses_shared_grader_and_reports_failure(self, monkeypatch):
        check, brief = _check_and_brief()
        session = FakeSession(check, brief)
        grade = AsyncMock(side_effect=RuntimeError("internal detail"))
        monkeypatch.setattr(
            "ui.backend.services.saved_brief_check_runner.run_full_check", grade
        )
        await runner.run_check(check.id, session_factory=lambda: session)
        grade.assert_awaited_once_with(session, check)
        # The failed flush may have left a dead transaction: rolled back first.
        assert session.rollbacks == 1
        assert check.summary_stats == {"error": "Check failed"}

    @pytest.mark.asyncio
    async def test_full_check_when_cancelled_before_failing_then_cancel_kept(
        self, monkeypatch
    ):
        check, brief = _check_and_brief()
        session = FakeSession(check, brief)

        async def grade(session_, check_):
            # The cancel route (or orphan recovery on another api copy) flips
            # the row while the grader is out, then the grader fails.
            check_.status = "failed"
            check_.summary_stats = {"error": "Cancelled by user"}
            raise RuntimeError("judge gone")

        monkeypatch.setattr(
            "ui.backend.services.saved_brief_check_runner.run_full_check", grade
        )
        await runner.run_check(check.id, session_factory=lambda: session)
        assert check.summary_stats == {"error": "Cancelled by user"}

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


class TestStaleChecks:
    @pytest.mark.asyncio
    async def test_fail_stale_when_no_heartbeat_then_failed_with_reason(self):
        old = NOW - timedelta(minutes=40)
        orphan, brief = _check_and_brief(
            status="running",
            started_at=old,
            created_at=old,
            summary_stats=progress_stats(4, 9, now=old),
        )
        alive, _ = _check_and_brief(
            status="running",
            started_at=old,
            created_at=old,
            summary_stats=progress_stats(4, 9, now=NOW - timedelta(minutes=1)),
        )
        stuck, _ = _check_and_brief(status="pending", created_at=old)
        done, _ = _check_and_brief(status="completed", created_at=old)
        session = FakeSession(orphan, brief, checks=[alive, stuck, done])

        assert await runner.fail_stale_checks(session, now=NOW) == 2
        assert orphan.status == "failed" and orphan.finished_at == NOW
        assert orphan.summary_stats["error"].startswith("no progress for 40 min")
        assert stuck.status == "failed"
        assert (
            alive.status == "running"
            and alive.summary_stats["progress"]["completed"] == 4
        )
        assert done.status == "completed"
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_fail_stale_when_nothing_stale_then_no_commit(self):
        check, brief = _check_and_brief(status="running", started_at=NOW)
        session = FakeSession(check, brief)
        assert await runner.fail_stale_checks(session, now=NOW) == 0
        assert session.commits == 0 and check.status == "running"

    @pytest.mark.asyncio
    async def test_recover_orphaned_when_called_then_sweeps_through_factory(self):
        old = NOW - timedelta(hours=1)
        check, brief = _check_and_brief(
            status="running", started_at=old, created_at=old
        )
        session = FakeSession(check, brief)
        await runner.recover_orphaned_checks(session_factory=lambda: session)
        assert check.status == "failed"


class TestReferenceLines:
    def test_count_skipped_when_section_has_reference_list_then_counted(self):
        content = convert_legacy(
            {
                "sections": [
                    {
                        "title": "S",
                        "status": "done",
                        "content": "Fact [1].\n\n[1] WFP. 2023. Report.\n[2] WFP. 2024. Other.",
                        "sources": [SOURCE],
                    }
                ]
            }
        )[0]
        assert runner.count_skipped_reference_lines(content) == 2
        assert runner.count_cited_passages(content) == 1
        assert runner.count_skipped_reference_lines(BRIEF) == 0


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
