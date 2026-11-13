"""Unit tests for the brief citation check runner (judge and DB faked)."""

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook
from sqlalchemy import Select

from ui.backend.services import citation_check_runner as runner
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.services.citation_fidelity import CitedPassage

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

    def test_judge_prompts_when_rendered_then_excerpt_and_quotes_unescaped(self):
        system, user = runner.judge_prompts(_passage(passage='Dropout "fell" [1].'))
        assert system.startswith("You are a meticulous fact-checker")
        assert 'Dropout "fell"' in user and "&quot;" not in user
        assert EXCERPT in user and '[1] document: "Kenya evaluation", p. 4' in user


class TestPassageRecord:
    def test_record_when_reply_valid_then_verdict_and_quote_verified(self):
        judgement = runner.judgement_or_error(_passage(), GOOD_REPLY)
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
        record = runner.passage_record(
            1, _passage(), runner.judgement_or_error(_passage(), reply)
        )
        assert record["quote_not_in_source"] is True
        assert record["supporting_quotes"][0]["status"] == "missing"

    def test_record_when_reply_malformed_then_cannot_assess_with_visible_error(self):
        judgement = runner.judgement_or_error(_passage(), "not json at all")
        record = runner.passage_record(
            1, _passage(), judgement, error=judgement["problems"][0]
        )
        assert record["verdict"] == "cannot_assess" and record["flagged"] is True
        assert record["error_message"].startswith("JUDGE ERROR")

    def test_record_when_dangling_citation_then_problem_added(self):
        passage = _passage(citation_indices=[1, 2], missing_indices=[2])
        judgement = runner.judgement_or_error(passage, GOOD_REPLY)
        record = runner.passage_record(1, passage, judgement)
        assert record["dangling_citations"] == "2"
        assert any("Dangling citation(s) [2]" in p for p in record["problems"])


class TestJudgePassage:
    @pytest.mark.asyncio
    async def test_judge_when_no_sources_then_not_sent_to_judge(self):
        calls = []

        async def judge(system, user):
            calls.append(user)
            return GOOD_REPLY, {}

        passage = _passage(sources=[], missing_indices=[1])
        record = await runner.judge_passage(1, passage, judge, asyncio.Semaphore(1))
        assert calls == []
        assert record["verdict"] == "cannot_assess"
        assert "No source stored for citation(s) [1]" in record["error_message"]

    @pytest.mark.asyncio
    async def test_judge_when_call_raises_then_error_row_not_exception(self):
        async def judge(system, user):
            raise RuntimeError("provider down")

        record = await runner.judge_passage(1, _passage(), judge, asyncio.Semaphore(1))
        assert record["verdict"] == "cannot_assess"
        assert record["error_message"] == "JUDGE ERROR: the model call failed"
        assert "provider down" not in record["error_message"]


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
        status=status,
        summary_stats=None,
        started_at=None,
        finished_at=None,
        created_at=NOW,
    )
    return SimpleNamespace(**{**fields, **over}), brief


class TestRunCheck:
    @pytest.mark.asyncio
    async def test_run_when_judge_answers_then_rows_committed_and_completed(
        self, monkeypatch
    ):
        recorded = []

        async def fake_record(**kwargs):
            recorded.append(kwargs)

        monkeypatch.setattr(
            "ui.backend.services.usage_recorder.record_llm_usage", fake_record
        )
        monkeypatch.setattr(
            "ui.backend.utils.llm_costs.compute_cost", lambda m, p, c: None
        )
        check, brief = _check_and_brief()
        session = FakeSession(check, brief)

        async def judge(system, user):
            return GOOD_REPLY, {"prompt_tokens": 7, "completion_tokens": 3}

        await runner.run_check(check.id, session_factory=lambda: session, judge=judge)
        assert check.status == "completed"
        assert check.started_at is not None and check.finished_at is not None
        assert [
            r.passage_id for r in sorted(session.added, key=lambda r: r.passage_id)
        ] == [1, 2]
        by_id = {r.passage_id: r for r in session.added}
        assert by_id[1].verdict == "supported"
        assert by_id[2].verdict == "cannot_assess"  # no source stored for [2]
        stats = check.summary_stats
        assert (
            stats["total"] == 2
            and stats["flagged"] == 1
            and stats["prompt_tokens"] == 7
        )
        assert stats["reference_lines_skipped"] == 0
        assert recorded and recorded[0]["activity_type"] == "evaluation"
        assert recorded[0]["search_id"] == check.id
        assert session.rollbacks == 0

    @pytest.mark.asyncio
    async def test_run_when_progress_written_then_each_write_carries_heartbeat(self):
        check, brief = _check_and_brief()
        session = FakeSession(check, brief)
        seen = []

        async def judge(system, user):
            seen.append(check.summary_stats["progress"])
            return GOOD_REPLY, {}

        await runner.run_check(check.id, session_factory=lambda: session, judge=judge)
        # The claim wrote 0 of 2 with a stamp before the first judge call.
        assert seen[0]["completed"] == 0 and seen[0]["total"] == 2
        assert datetime.fromisoformat(seen[0]["at"]).tzinfo is not None

    @pytest.mark.asyncio
    async def test_run_when_brief_missing_then_failed_with_message(self):
        check, brief = _check_and_brief()
        session = FakeSession(check, brief)
        session.brief = None
        await runner.run_check(check.id, session_factory=lambda: session)
        assert check.status == "failed"
        assert check.summary_stats == {"error": "Brief not found"}

    @pytest.mark.asyncio
    async def test_run_when_cancelled_midway_then_stops_and_keeps_cancel_record(
        self,
    ):
        check, brief = _check_and_brief()
        session = FakeSession(check, brief)

        async def judge(system, user):
            # The cancel route (or orphan recovery on another api copy) flips
            # the row while the judge is out.
            check.status = "failed"
            check.summary_stats = {"error": "Cancelled by user"}
            return GOOD_REPLY, {}

        await runner.run_check(check.id, session_factory=lambda: session, judge=judge)
        assert check.status == "failed"
        assert check.summary_stats == {"error": "Cancelled by user"}
        assert session.added == [] and session.rollbacks >= 1

    @pytest.mark.asyncio
    async def test_run_when_no_longer_pending_then_not_started(self):
        check, brief = _check_and_brief(status="failed", summary_stats={"error": "x"})
        session = FakeSession(check, brief)
        calls = []

        async def judge(system, user):
            calls.append(user)
            return GOOD_REPLY, {}

        await runner.run_check(check.id, session_factory=lambda: session, judge=judge)
        assert calls == [] and session.added == [] and session.commits == 0
        assert check.summary_stats == {"error": "x"}

    @pytest.mark.asyncio
    async def test_run_when_execution_raises_then_generic_failure(self, monkeypatch):
        check, brief = _check_and_brief()
        session = FakeSession(check, brief)
        monkeypatch.setattr(runner, "brief_passages", lambda content: 1 / 0)
        await runner.run_check(check.id, session_factory=lambda: session)
        assert check.status == "failed"
        assert check.summary_stats == {"error": "Check failed"}


class TestStaleChecks:
    @pytest.mark.asyncio
    async def test_fail_stale_when_no_heartbeat_then_failed_with_reason(self):
        old = NOW - timedelta(minutes=40)
        orphan, brief = _check_and_brief(
            status="running",
            started_at=old,
            created_at=old,
            summary_stats=runner.progress_stats(4, 9, now=old),
        )
        alive, _ = _check_and_brief(
            status="running",
            started_at=old,
            created_at=old,
            summary_stats=runner.progress_stats(4, 9, now=NOW - timedelta(minutes=1)),
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
        assert runner.resolve_judge_model("X") == "combo-model"
        assert runner.resolve_judge_model(None) == "default"
