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
from ui.backend.services import brief_versions as bv
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.utils.app_limits import limiter

pytestmark = pytest.mark.unit
limiter.enabled = False

NOW = datetime.now(timezone.utc)
FACT = "A fact."
OTHER = "Another claim."
WHY = "The excerpt says the opposite."


COST = "Costs rose."


def _section(sid, title, text):
    return {
        "id": sid,
        "title": title,
        "status": "done",
        "content": text,
        "sources": [
            {"index": 1, "title": "Doc", "text": "text", "chunkId": "c1", "docId": "d1"}
        ],
    }


def _content(text="A fact [1]. Another claim [1].", second=None):
    """A brief with one researched section, or two when ``second`` is the
    text of a second one."""
    sections = [_section("s1", "Findings", text)]
    if second is not None:
        sections.append(_section("s2", "Costs", second))
    return convert_legacy({"sections": sections})[0]


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


def _check(brief_id, rows, status="completed", age=0, version=None, stats=None):
    """A check; ``version`` is the version row it pinned (None for a check
    made before versions were linked)."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        brief_id=brief_id,
        brief_title="B",
        data_source="wfp",
        created_by_user_id=None,
        judge_model="m",
        model_combo=None,
        brief_version_id=version.id if version else None,
        brief_version_number=version.number if version else None,
        status=status,
        summary_stats=stats,
        started_at=None,
        finished_at=None,
        created_at=NOW - timedelta(minutes=age),
        passages=list(rows),
    )


def _version(brief_id, content, number=1):
    """A brief_versions row holding ``content`` as the version Log stores it."""
    return SimpleNamespace(
        id=uuid.uuid4(), brief_id=brief_id, number=number, content=bv.snapshot(content)
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
# Matching a check to a brief
# ---------------------------------------------------------------------------


class TestJudgedPassages:
    def test_passages_carry_their_section_id_in_order(self):
        passages = svc.current_passages(_content())
        assert [(sid, p.passage_clean) for sid, p in passages] == [
            ("s1", FACT),
            ("s1", OTHER),
        ]

    def test_rows_are_placed_in_their_sections_in_passage_order(self):
        judged = svc.judged_passages(_content(), list(reversed(MATCHING_ROWS)))
        assert [(sid, p.passage_clean, row.passage_id) for sid, p, row in judged] == [
            ("s1", FACT, 1),
            ("s1", OTHER, 2),
        ]

    def test_when_a_passage_was_edited_then_the_content_is_not_what_was_judged(
        self,
    ):
        edited = _content("A changed fact [1]. Another claim [1].")
        assert svc.judged_passages(edited, MATCHING_ROWS) is None

    def test_when_a_passage_was_added_then_the_content_is_not_what_was_judged(self):
        longer = _content("A fact [1]. Another claim [1]. New [1].")
        assert svc.judged_passages(longer, MATCHING_ROWS) is None


TWO_SECTION_ROWS = MATCHING_ROWS + [_row(3, COST, "partially_supported")]


class TestCoverage:
    def test_a_section_still_reading_as_judged_is_covered_and_a_changed_one_is_not(
        self,
    ):
        judged = svc.judged_passages(
            _content(second="Costs rose [1]."), TWO_SECTION_ROWS
        )
        now = _content(second="Costs fell [1].")
        cov = svc.coverage(now, judged)
        assert list(cov.covered) == ["s1"]
        assert [(p.passage_clean, row.passage_id) for p, row in cov.covered["s1"]] == [
            (FACT, 1),
            (OTHER, 2),
        ]
        assert cov.changed == [{"id": "s2", "title": "Costs"}]

    def test_a_section_added_since_the_check_is_changed(self):
        judged = svc.judged_passages(_content(), MATCHING_ROWS)
        cov = svc.coverage(_content(second="New [1]."), judged)
        assert list(cov.covered) == ["s1"] and [s["id"] for s in cov.changed] == ["s2"]

    def test_a_section_without_cited_passages_is_neither(self):
        judged = svc.judged_passages(_content(), MATCHING_ROWS)
        cov = svc.coverage(_content(second="No citation here."), judged)
        assert list(cov.covered) == ["s1"] and cov.changed == []

    def test_a_section_removed_since_the_check_is_simply_gone(self):
        judged = svc.judged_passages(
            _content(second="Costs rose [1]."), TWO_SECTION_ROWS
        )
        cov = svc.coverage(_content(), judged)
        assert list(cov.covered) == ["s1"] and cov.changed == []


class FakeSession:
    """Answers the route's queries from in-memory lists."""

    def __init__(self, briefs=(), checks=(), shares=(), groups=(), versions=()):
        self.briefs, self.checks = list(briefs), list(checks)
        self.shares, self.groups = list(shares), list(groups)
        self.versions = list(versions)
        self.refreshed = []

    async def execute(self, statement):
        text = str(statement)
        tuples = None
        if "FROM briefs" in text:
            rows = self.briefs
        elif "FROM brief_shares" in text:
            rows = self.shares
        elif "FROM brief_citation_checks" in text:
            assert "status" in text, "only completed checks are candidates"
            assert "LIMIT" in text, "only the newest completed check is read"
            rows = sorted(
                (c for c in self.checks if c.status == "completed"),
                key=lambda c: c.created_at,
                reverse=True,
            )
        elif "FROM brief_versions" in text:
            assert "max(" in text, "only the current version number is read"
            numbers = {}
            for v in self.versions:
                numbers[v.brief_id] = max(numbers.get(v.brief_id, 0), v.number)
            rows, tuples = [], list(numbers.items())
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

        # ``.all()`` serves ``user_group_ids`` (row tuples) and
        # ``latest_numbers`` ((brief id, number) tuples).
        return SimpleNamespace(
            scalars=lambda: Scalars(rows),
            all=lambda: tuples if tuples is not None else [(r,) for r in rows],
        )

    async def get(self, model, key):
        assert model.__name__ == "BriefVersion"
        return next((v for v in self.versions if v.id == key), None)

    async def refresh(self, row, attribute_names=None):
        self.refreshed.append(row)


def _checked_brief(owner_id, now_text="Costs rose [1].", rows=TWO_SECTION_ROWS):
    """A two-section brief checked at version 1 and now at version 2, where
    the second section reads ``now_text``; returns (brief, check, session)."""
    judged = _content(second="Costs rose [1].")
    brief = _brief(owner_id, content=_content(second=now_text))
    v1 = _version(brief.id, judged, 1)
    v2 = _version(brief.id, brief.content, 2)
    check = _check(brief.id, rows, version=v1)
    return brief, check, FakeSession(briefs=[brief], checks=[check], versions=[v1, v2])


class TestFactCheck:
    @pytest.mark.asyncio
    async def test_when_no_completed_check_then_nothing(self):
        brief = _brief(uuid.uuid4())
        pending = _check(brief.id, [], status="running")
        session = FakeSession(briefs=[brief], checks=[pending])
        out = await svc.fact_check(session, brief, ["unsupported"])
        assert out["check"] is None and out["marks"] == []
        assert session.refreshed == []

    @pytest.mark.asyncio
    async def test_a_section_changed_since_the_check_loses_its_marks_and_is_named(
        self,
    ):
        brief, check, session = _checked_brief(uuid.uuid4(), "Costs fell [1].")
        out = await svc.fact_check(
            session, brief, ["unsupported", "partially_supported"]
        )
        assert out["check"] is check
        assert (out["brief_version"], out["current_version"]) == (1, 2)
        assert [(m["section_id"], m["passage"]) for m in out["marks"]] == [("s1", FACT)]
        assert out["changed_sections"] == [
            {
                "id": "s2",
                "title": "Costs",
                "note": "Changed since the citation check (version 1); not covered "
                "by the Fact Checker.",
            }
        ]
        assert out["note"] == (
            "Checked at version 1; the brief is now at version 2. 1 section changed "
            "since and is not highlighted: “Costs”."
        )

    @pytest.mark.asyncio
    async def test_a_newer_version_with_the_same_passages_keeps_every_mark(self):
        brief, check, session = _checked_brief(uuid.uuid4(), "Costs rose [1].")
        out = await svc.fact_check(session, brief, ["partially_supported"])
        assert [m["section_id"] for m in out["marks"]] == ["s2"]
        assert out["changed_sections"] == []
        assert out["note"] == (
            "Checked at version 1; the brief is now at version 2, with its cited "
            "passages unchanged since."
        )

    @pytest.mark.asyncio
    async def test_at_the_checked_version_the_note_says_so(self):
        brief = _brief(uuid.uuid4())
        v1 = _version(brief.id, brief.content, 1)
        check = _check(brief.id, MATCHING_ROWS, version=v1)
        session = FakeSession(briefs=[brief], checks=[check], versions=[v1])
        out = await svc.fact_check(session, brief, ["unsupported"])
        assert out["note"] == "Checked at version 1, the brief's current version."
        assert out["check"].brief_version_number == 1

    @pytest.mark.asyncio
    async def test_when_every_section_changed_then_nothing(self):
        brief, _check_, session = _checked_brief(uuid.uuid4(), "Costs fell [1].")
        brief.content = _content("A new fact [1].", second="Costs fell [1].")
        out = await svc.fact_check(session, brief, ["unsupported"])
        assert out["check"] is None and out["current_version"] == 2

    @pytest.mark.asyncio
    async def test_the_newest_completed_check_is_the_one_that_applies(self):
        brief = _brief(uuid.uuid4())
        v1 = _version(brief.id, brief.content, 1)
        older = _check(brief.id, MATCHING_ROWS, version=v1, age=5)
        newer = _check(
            brief.id,
            [_row(1, FACT, "supported"), _row(2, OTHER, "supported")],
            version=v1,
        )
        session = FakeSession(briefs=[brief], checks=[older, newer], versions=[v1])
        out = await svc.fact_check(session, brief, ["unsupported"])
        assert out["check"] is newer and out["marks"] == []

    @pytest.mark.asyncio
    async def test_marks_cite_the_numbers_readers_see_now(self):
        brief, _check_, session = _checked_brief(uuid.uuid4())
        out = await svc.fact_check(session, brief, ["unsupported"])
        assert out["marks"][0]["citations"] == "1"

    @pytest.mark.asyncio
    async def test_a_check_that_does_not_match_its_version_is_an_error(self):
        brief = _brief(uuid.uuid4())
        v1 = _version(brief.id, _content("Other prose [1]."), 1)
        check = _check(brief.id, MATCHING_ROWS, version=v1)
        session = FakeSession(briefs=[brief], checks=[check], versions=[v1])
        with pytest.raises(svc.FactCheckError, match="does not match brief version 1"):
            await svc.fact_check(session, brief, ["unsupported"])

    @pytest.mark.asyncio
    async def test_a_check_whose_version_is_missing_is_an_error(self):
        brief = _brief(uuid.uuid4())
        check = _check(
            brief.id, MATCHING_ROWS, version=_version(brief.id, brief.content)
        )
        session = FakeSession(briefs=[brief], checks=[check])
        with pytest.raises(svc.FactCheckError, match="does not exist"):
            await svc.fact_check(session, brief, ["unsupported"])


class TestChecksBeforeVersionsWereLinked:
    @pytest.mark.asyncio
    async def test_applies_while_the_whole_brief_reads_as_judged(self):
        brief = _brief(uuid.uuid4())
        check = _check(brief.id, MATCHING_ROWS)
        session = FakeSession(briefs=[brief], checks=[check])
        out = await svc.fact_check(session, brief, ["unsupported"])
        assert out["check"] is check and out["brief_version"] is None
        assert [m["passage"] for m in out["marks"]] == [FACT]
        assert out["note"].startswith("Checked before version history began")

    @pytest.mark.asyncio
    async def test_once_any_passage_changed_it_no_longer_applies(self):
        brief = _brief(uuid.uuid4(), content=_content(second="Costs rose [1]."))
        check = _check(brief.id, MATCHING_ROWS)
        session = FakeSession(briefs=[brief], checks=[check])
        out = await svc.fact_check(session, brief, ["unsupported"])
        assert out["check"] is None


class TestFactCheckMarks:
    def test_only_chosen_verdicts_with_section_and_reasoning(self):
        cov = svc.coverage(_content(), svc.judged_passages(_content(), MATCHING_ROWS))
        assert svc.fact_check_marks(cov, ["unsupported"]) == [
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
        cov = svc.coverage(_content(), svc.judged_passages(_content(), MATCHING_ROWS))
        marks = svc.fact_check_marks(cov, ["unsupported", "supported"])
        assert [m["verdict_label"] for m in marks] == ["Unsupported", "Supported"]

    def test_when_no_verdict_chosen_then_no_marks(self):
        cov = svc.coverage(_content(), svc.judged_passages(_content(), MATCHING_ROWS))
        assert svc.fact_check_marks(cov, []) == []


class TestVersionLogChecks:
    def test_brief_changed_compares_version_numbers(self):
        v = _version(uuid.uuid4(), _content(), 3)
        check = _check(uuid.uuid4(), [], version=v)
        assert svc.brief_changed(check, 3) is False
        assert svc.brief_changed(check, 4) is True
        assert svc.brief_changed(_check(uuid.uuid4(), []), 4) is None

    def test_a_completed_check_is_labelled_by_its_counts(self):
        check = _check(uuid.uuid4(), [], stats={"total": 12, "flagged": 3})
        assert svc.version_check(check) == {
            "id": check.id,
            "status": "completed",
            "created_at": check.created_at,
            "flagged": 3,
            "total": 12,
            "label": "Citation check: 3 of 12 passages flagged",
        }
        running = _check(uuid.uuid4(), [], status="running")
        assert svc.version_check(running)["label"] == "Citation check running"
        assert svc.version_check(None) is None

    @pytest.mark.asyncio
    async def test_each_version_names_its_newest_check(self):
        brief = _brief(uuid.uuid4())
        v1, v2 = _version(brief.id, brief.content, 1), _version(
            brief.id, brief.content, 2
        )
        old = _check(brief.id, [], version=v1, age=10)
        new = _check(brief.id, [], version=v1, age=5)
        other = _check(brief.id, [], version=v2, status="failed")

        class Session:
            async def execute(self, statement):
                assert "brief_version_id IS NOT NULL" in str(statement)
                rows = sorted(
                    [old, new, other], key=lambda c: c.created_at, reverse=True
                )
                return SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: rows)
                )

        assert await svc.checks_by_version(Session(), brief.id) == {
            v1.id: new,
            v2.id: other,
        }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class TestRoute:
    @pytest.mark.asyncio
    async def test_owner_gets_the_check_its_versions_and_marks(self):
        me = _user()
        brief, check, session = _checked_brief(me.id, "Costs fell [1].")
        out = await routes.get_brief_fact_check(
            brief.id, _request(), user=me, session=session
        )
        assert out.check is not None and out.check.id == check.id
        assert out.check.brief_version_number == 1 and out.check.brief_changed is True
        assert (out.brief_version, out.current_version) == (1, 2)
        assert out.highlight_verdicts == ["unsupported"]
        assert [(m.section_id, m.passage) for m in out.marks] == [("s1", FACT)]
        assert [(s.id, s.title) for s in out.changed_sections] == [("s2", "Costs")]
        assert out.note.startswith(
            "Checked at version 1; the brief is now at version 2."
        )

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
    async def test_when_no_check_applies_then_nothing_to_show(self):
        me = _user()
        brief = _brief(me.id)
        stale = _check(brief.id, [_row(1, "Old prose.", "unsupported")])
        session = FakeSession(briefs=[brief], checks=[stale])
        out = await routes.get_brief_fact_check(
            brief.id, _request(), user=me, session=session
        )
        assert out.check is None
        assert out.marks == [] and out.changed_sections == [] and out.note == ""
        assert out.highlight_verdicts == ["unsupported"]

    @pytest.mark.asyncio
    async def test_a_check_that_does_not_match_its_version_is_a_bad_request(self):
        me = _user()
        brief = _brief(me.id)
        v1 = _version(brief.id, _content("Other prose [1]."), 1)
        check = _check(brief.id, MATCHING_ROWS, version=v1)
        session = FakeSession(briefs=[brief], checks=[check], versions=[v1])
        with pytest.raises(HTTPException) as exc:
            await routes.get_brief_fact_check(
                brief.id, _request(), user=me, session=session
            )
        assert exc.value.status_code == 400

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
