"""Unit tests for the brief Fact Checker (service and route; DB faked)."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from ui.backend.auth.schemas import GroupUpdate, SearchSettings
from ui.backend.routes import brief_central as routes
from ui.backend.services import brief_fact_check as svc
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.utils.app_limits import limiter

pytestmark = pytest.mark.unit
limiter.enabled = False

NOW = datetime.now(timezone.utc)
FACT = "A fact."
OTHER = "Another claim."
WHY = "The excerpt says the opposite."


def _content(text="A fact [1]. Another claim [1]."):
    return convert_legacy(
        {
            "sections": [
                {
                    "id": "s1",
                    "title": "Findings",
                    "status": "done",
                    "content": text,
                    "sources": [
                        {
                            "index": 1,
                            "title": "Doc",
                            "text": "text",
                            "chunkId": "c1",
                            "docId": "d1",
                        }
                    ],
                }
            ]
        }
    )[0]


def _row(pid, passage, verdict, **over):
    fields = dict(
        passage_id=pid,
        passage=passage,
        verdict=verdict,
        explanation=WHY if verdict != "supported" else "Stated in the excerpt.",
        problems=["Contradicted"] if verdict == "unsupported" else [],
        confidence=0.9,
        citations="1",
        quote_not_in_source=False,
    )
    return SimpleNamespace(**{**fields, **over})


def _check(brief_id, rows, status="completed", age=0):
    return SimpleNamespace(
        id=uuid.uuid4(),
        brief_id=brief_id,
        brief_title="B",
        data_source="wfp",
        created_by_user_id=None,
        judge_model="m",
        model_combo=None,
        status=status,
        summary_stats=None,
        started_at=None,
        finished_at=None,
        created_at=NOW - timedelta(minutes=age),
        passages=list(rows),
    )


def _user(superuser=False):
    return SimpleNamespace(id=uuid.uuid4(), is_superuser=superuser, email="j@x")


def _brief(owner_id, content=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=owner_id,
        title="B",
        content=content if content is not None else _content(),
    )


def _request():
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 1),
            "app": FastAPI(),
        }
    )


MATCHING_ROWS = [_row(1, FACT, "unsupported"), _row(2, OTHER, "supported")]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestHighlightVerdicts:
    def test_when_no_group_set_it_then_unsupported_only(self):
        assert svc.highlight_verdicts({}) == ["unsupported"]
        assert svc.highlight_verdicts(None) == ["unsupported"]

    def test_when_group_chose_verdicts_then_those_in_order_once(self):
        settings = {
            svc.FACT_CHECK_SETTING_KEY: [
                "partially_supported",
                "unsupported",
                "partially_supported",
            ]
        }
        assert svc.highlight_verdicts(settings) == [
            "partially_supported",
            "unsupported",
        ]

    def test_when_group_chose_none_then_nothing_highlighted(self):
        assert svc.highlight_verdicts({svc.FACT_CHECK_SETTING_KEY: []}) == []

    @pytest.mark.parametrize("bad", [["maybe"], "unsupported", [1]])
    def test_when_value_unknown_then_error(self, bad):
        with pytest.raises(ValueError):
            svc.validate_verdicts(bad)

    def test_group_update_rejects_unknown_verdict(self):
        with pytest.raises(ValidationError):
            GroupUpdate(search_settings={svc.FACT_CHECK_SETTING_KEY: ["maybe"]})

    def test_group_update_keeps_valid_verdicts_and_other_keys(self):
        body = GroupUpdate(
            search_settings={
                "rerank": False,
                svc.FACT_CHECK_SETTING_KEY: ["unsupported", "cannot_assess"],
            }
        )
        assert body.search_settings == {
            "rerank": False,
            svc.FACT_CHECK_SETTING_KEY: ["unsupported", "cannot_assess"],
        }
        assert GroupUpdate(search_settings={"rerank": True}).search_settings == {
            "rerank": True
        }
        assert SearchSettings(
            briefFactCheckVerdicts=["unsupported"]
        ).briefFactCheckVerdicts == ["unsupported"]


# ---------------------------------------------------------------------------
# Matching a check to the brief's current passages
# ---------------------------------------------------------------------------


class TestCurrentPassages:
    def test_passages_carry_their_section_id_in_order(self):
        passages = svc.current_passages(_content())
        assert [(sid, p.passage_clean) for sid, p in passages] == [
            ("s1", FACT),
            ("s1", OTHER),
        ]

    def test_when_check_judged_the_same_prose_then_matches(self):
        assert svc.check_matches(svc.current_passages(_content()), MATCHING_ROWS)

    def test_rows_are_compared_in_passage_order(self):
        assert svc.check_matches(
            svc.current_passages(_content()), list(reversed(MATCHING_ROWS))
        )

    def test_when_a_passage_was_edited_then_stale(self):
        edited = _content("A changed fact [1]. Another claim [1].")
        assert not svc.check_matches(svc.current_passages(edited), MATCHING_ROWS)

    def test_when_a_passage_was_added_then_stale(self):
        longer = _content("A fact [1]. Another claim [1]. New [1].")
        assert not svc.check_matches(svc.current_passages(longer), MATCHING_ROWS)


class FakeSession:
    """Answers the route's queries from in-memory lists."""

    def __init__(self, briefs=(), checks=(), shares=(), groups=()):
        self.briefs, self.checks = list(briefs), list(checks)
        self.shares, self.groups = list(shares), list(groups)
        self.refreshed = []

    async def execute(self, statement):
        text = str(statement)
        if "FROM briefs" in text:
            rows = self.briefs
        elif "FROM brief_shares" in text:
            rows = self.shares
        elif "FROM brief_citation_checks" in text:
            assert "status" in text, "only completed checks are candidates"
            rows = sorted(self.checks, key=lambda c: c.created_at, reverse=True)
        elif "FROM user_groups JOIN user_group_members" in text:
            rows = self.groups
        elif "FROM user_group_members" in text:
            rows = []
        else:
            raise AssertionError(f"unexpected query: {text[:80]}")

        class Scalars(list):
            def all(self):
                return list(self)

            def first(self):
                return self[0] if self else None

        # ``.all()`` serves ``user_group_ids``, which reads row tuples.
        return SimpleNamespace(
            scalars=lambda: Scalars(rows), all=lambda: [(r,) for r in rows]
        )

    async def refresh(self, row, attribute_names=None):
        self.refreshed.append(row)


class TestCurrentCheck:
    @pytest.mark.asyncio
    async def test_when_brief_has_no_cited_passages_then_none_without_a_query(self):
        brief = _brief(uuid.uuid4(), content=_content("No citations here."))
        assert await svc.current_check(FakeSession(), brief) is None

    @pytest.mark.asyncio
    async def test_newest_matching_completed_check_wins(self):
        brief = _brief(uuid.uuid4())
        stale = _check(brief.id, [_row(1, "Old prose.", "unsupported")], age=0)
        older_match = _check(brief.id, MATCHING_ROWS, age=5)
        session = FakeSession(checks=[older_match, stale])
        assert await svc.current_check(session, brief) is older_match
        # The stale check was examined (its passages loaded) and passed over.
        assert session.refreshed == [stale, older_match]

    @pytest.mark.asyncio
    async def test_when_no_check_matches_then_none(self):
        brief = _brief(uuid.uuid4())
        stale = _check(brief.id, [_row(1, "Old prose.", "unsupported")])
        assert await svc.current_check(FakeSession(checks=[stale]), brief) is None


class TestFactCheckMarks:
    def test_only_chosen_verdicts_with_section_and_reasoning(self):
        check = _check(uuid.uuid4(), MATCHING_ROWS)
        marks = svc.fact_check_marks(_content(), check, ["unsupported"])
        assert marks == [
            {
                "passage_id": 1,
                "section_id": "s1",
                "section_title": "Findings",
                "passage": FACT,
                "verdict": "unsupported",
                "verdict_label": "Unsupported",
                "explanation": WHY,
                "problems": ["Contradicted"],
                "confidence": 0.9,
                "citations": "1",
                "quote_not_in_source": False,
            }
        ]

    def test_every_verdict_can_be_highlighted(self):
        check = _check(uuid.uuid4(), MATCHING_ROWS)
        marks = svc.fact_check_marks(_content(), check, ["unsupported", "supported"])
        assert [m["verdict_label"] for m in marks] == ["Unsupported", "Supported"]

    def test_when_no_verdict_chosen_then_no_marks(self):
        check = _check(uuid.uuid4(), MATCHING_ROWS)
        assert svc.fact_check_marks(_content(), check, []) == []


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class TestRoute:
    @pytest.mark.asyncio
    async def test_owner_gets_the_current_check_and_marks(self):
        me = _user()
        brief = _brief(me.id)
        check = _check(brief.id, MATCHING_ROWS)
        session = FakeSession(briefs=[brief], checks=[check])
        out = await routes.get_brief_fact_check(
            brief.id, _request(), user=me, session=session
        )
        assert out.check is not None and out.check.id == check.id
        assert out.highlight_verdicts == ["unsupported"]
        assert [(m.section_id, m.passage) for m in out.marks] == [("s1", FACT)]

    @pytest.mark.asyncio
    async def test_group_setting_decides_the_highlighted_verdicts(self):
        me = _user()
        brief = _brief(me.id)
        check = _check(brief.id, MATCHING_ROWS)
        group = SimpleNamespace(
            search_settings={svc.FACT_CHECK_SETTING_KEY: ["supported"]}
        )
        session = FakeSession(briefs=[brief], checks=[check], groups=[group])
        out = await routes.get_brief_fact_check(
            brief.id, _request(), user=me, session=session
        )
        assert out.highlight_verdicts == ["supported"]
        assert [m.passage for m in out.marks] == [OTHER]

    @pytest.mark.asyncio
    async def test_when_no_current_check_then_nothing_to_show(self):
        me = _user()
        brief = _brief(me.id)
        stale = _check(brief.id, [_row(1, "Old prose.", "unsupported")])
        session = FakeSession(briefs=[brief], checks=[stale])
        out = await routes.get_brief_fact_check(
            brief.id, _request(), user=me, session=session
        )
        assert out.check is None
        assert out.marks == []
        assert out.highlight_verdicts == ["unsupported"]

    @pytest.mark.asyncio
    async def test_a_viewer_the_brief_was_shared_with_sees_it(self):
        viewer = _user()
        brief = _brief(uuid.uuid4())
        check = _check(brief.id, MATCHING_ROWS)
        session = FakeSession(briefs=[brief], checks=[check], shares=[uuid.uuid4()])
        out = await routes.get_brief_fact_check(
            brief.id, _request(), user=viewer, session=session
        )
        assert out.check is not None

    @pytest.mark.asyncio
    async def test_someone_without_access_gets_404(self):
        stranger = _user()
        brief = _brief(uuid.uuid4())
        session = FakeSession(briefs=[brief], checks=[_check(brief.id, MATCHING_ROWS)])
        with pytest.raises(HTTPException) as exc:
            await routes.get_brief_fact_check(
                brief.id, _request(), user=stranger, session=session
            )
        assert exc.value.status_code == 404
