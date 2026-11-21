"""Unit tests for ui/backend/services/job_liveness.py: the heartbeat, the
staleness rule and the conditional write that give a background job an
owner when several api copies share the database."""

import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import Select

from ui.backend.auth.testing_models import BriefCitationCheck
from ui.backend.services import job_liveness as liveness

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

NOW = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
STARTED = NOW - timedelta(hours=2)
CREATED = NOW - timedelta(hours=3)


def _progress(at: datetime):
    return liveness.progress_stats(3, 9, now=at)


class TestHeartbeat:
    async def test_progress_stats_when_built_then_counts_and_stamp(self):
        stats = _progress(NOW)
        assert stats["progress"]["completed"] == 3
        assert stats["progress"]["total"] == 9
        assert stats["progress"]["at"] == NOW.isoformat()

    async def test_progress_stats_when_no_time_given_then_stamped_now(self):
        at = datetime.fromisoformat(liveness.progress_stats(0, 1)["progress"]["at"])
        assert at.tzinfo is not None
        assert abs((liveness.utcnow() - at).total_seconds()) < 5

    async def test_last_activity_when_stamp_then_stamp_wins_over_dates(self):
        assert liveness.last_activity(_progress(NOW), STARTED, CREATED) == NOW

    async def test_last_activity_when_no_stamp_then_started_then_created(self):
        assert liveness.last_activity({"total": 3}, STARTED, CREATED) == STARTED
        assert liveness.last_activity(None, None, CREATED) == CREATED
        assert liveness.last_activity(None, None, None) is None

    async def test_last_activity_when_bad_stamp_or_naive_dates_then_tolerated(self):
        assert (
            liveness.last_activity({"progress": {"at": "soon"}}, STARTED, CREATED)
            == STARTED
        )
        naive = STARTED.replace(tzinfo=None)
        assert liveness.last_activity(None, naive, None) == STARTED


class TestStaleness:
    async def test_is_stale_when_fresh_heartbeat_then_false(self):
        recent = NOW - liveness.STALE_AFTER + timedelta(seconds=1)
        assert liveness.is_stale(_progress(recent), STARTED, CREATED, NOW) is False

    async def test_is_stale_when_heartbeat_at_limit_then_true(self):
        at_limit = NOW - liveness.STALE_AFTER
        assert liveness.is_stale(_progress(at_limit), STARTED, CREATED, NOW) is True

    async def test_is_stale_when_never_seen_then_true(self):
        assert liveness.is_stale(None, None, None, NOW) is True

    async def test_orphan_message_when_stale_then_names_the_silence(self):
        message = liveness.orphan_message(_progress(STARTED), STARTED, CREATED, NOW)
        assert message.startswith("no progress for 120 min")
        assert "orphaned task" in message
        assert liveness.orphan_message(None, None, None, NOW).startswith(
            "no progress recorded"
        )


class RecordingSession:
    """Answers a conditional UPDATE from one in-memory row and records what
    the caller did with the transaction."""

    def __init__(self, row):
        self.row = row
        self.commits = self.rollbacks = 0
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        params = statement.compile().params
        if (
            params.get("id_1") != self.row.id
            or self.row.status not in params["status_1"]
        ):
            return SimpleNamespace(rowcount=0)
        for key, value in params.items():
            if not re.search(r"_\d+$", key):
                setattr(self.row, key, value)
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class TestWriteWhile:
    async def test_write_while_when_status_matches_then_written_and_committed(self):
        row = SimpleNamespace(id=uuid.uuid4(), status="running", summary_stats=None)
        session = RecordingSession(row)
        ok = await liveness.write_while(
            session, BriefCitationCheck, row.id, ("running",), summary_stats={"a": 1}
        )
        assert ok is True
        assert row.summary_stats == {"a": 1}
        assert (session.commits, session.rollbacks) == (1, 0)
        assert not isinstance(session.statements[0], Select)

    async def test_write_while_when_status_changed_then_rolled_back_untouched(self):
        row = SimpleNamespace(
            id=uuid.uuid4(), status="failed", summary_stats={"error": "Cancelled"}
        )
        session = RecordingSession(row)
        ok = await liveness.write_while(
            session,
            BriefCitationCheck,
            row.id,
            ("running", "pending"),
            status="completed",
            summary_stats={"total": 1},
        )
        assert ok is False
        assert row.status == "failed" and row.summary_stats == {"error": "Cancelled"}
        assert (session.commits, session.rollbacks) == (0, 1)
