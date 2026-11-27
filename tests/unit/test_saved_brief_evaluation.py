"""Saved sections and experiments share the judge, grades and evidence numbering."""

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ui.backend.services import saved_brief_evaluation as saved
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.services.brief_experiment import judge_brief
from ui.backend.services.brief_fact_check import coverage, judged_passages
from ui.backend.services.test_evaluators import evaluate_assertion

pytestmark = pytest.mark.unit


def claim_rows(draft, checks, section_id):
    from ui.backend.services.brief_claim_records import bind_claims, claim_passages

    section = saved.section_result(draft, deepcopy(checks), section_id, False)
    bind_claims(section, uuid4(), 0)
    return [row for _, _, row in claim_passages([section])]


def brief_content():
    source = dict(
        index=3, title="Meter log", text="The reading doubled.", chunkId="c", docId="d"
    )
    heads = [
        dict(id="a", title="Results", level=1, content="The reading doubled [3]."),
        dict(
            id="b",
            title="Meter",
            level=2,
            content="The reading doubled [3]. Losses tripled.",
            targetWords=200,
        ),
        dict(id="c", title="Limitations", level=1, status="pending", content=""),
    ]
    return convert_legacy(
        dict(
            query="Test instruments",
            title="Readings",
            targetWords=350,
            instructions="Use SI units.",
            sections=[{"status": "done", "sources": [source], **s} for s in heads],
        )
    )[0]


def test_saved_snapshot_uses_section_overrides_children_and_complete_outline():
    content = brief_content()
    content["sections"][1]["voiceId"] = "gone"
    (intro, _, _), (child, _, missing), (empty, _, _) = saved.section_inputs(
        content, {}
    )
    assert intro["assignment"]["child_headings"] == ["Meter"]
    assert intro["assignment"]["target_words"] == saved.introduction_word_target()
    assert child["assignment"]["target_words"] == 200 and missing
    assert child["assignment"]["instructions"] == "Use SI units."
    assert child["siblings"][0]["content"] == intro["summary"]
    assert [
        intro["assignment"]["heading_number"],
        child["assignment"]["heading_number"],
    ] == ["1", "1.1"]
    assert not empty["written"]


@pytest.mark.asyncio
async def test_changed_and_deleted_profiles_cannot_grade_a_historical_version():
    at = datetime.now(timezone.utc)
    keys = [uuid4() for _ in range(3)]
    profiles = [
        SimpleNamespace(
            id=k, name="House style", instructions="Use SI units.", updated_at=t
        )
        for k, t in zip(keys, [at, at + timedelta(seconds=1)])
    ]
    session = AsyncMock()
    session.scalars.return_value = profiles
    content = {"sections": [{"voiceId": str(k)} for k in keys]}
    found = await saved.version_profiles(session, content, at)
    assert set(found) == {str(keys[0])}
    assert found[str(keys[0])]["instructions"] == "Use SI units."


@pytest.mark.asyncio
async def test_factual_prompt_and_grade_match_experiment_and_marks_include_uncited_claim(
    monkeypatch,
):
    from ui.backend.services import test_runner

    content = brief_content()
    draft, sid, _ = list(saved.section_inputs(content, {}))[1]
    factual = next(
        a for a in saved.DEFAULT_BRIEF_EXPECTATIONS if a["type"] == "brief_factual"
    )
    reply = (
        '{"claims":[{"claim":1,"score":1,"reason":"Matches the log.",'
        '"factual":true,"unmet":[],"supporting_quotes":[{"citation":1,"quote":"reading doubled"}]},'
        '{"claim":2,"score":0,"reason":"No source.","factual":true,"unmet":["Losses tripled"]}]}',
        {},
    )
    call = AsyncMock(return_value=reply)
    monkeypatch.setattr(test_runner, "_judge_call", call)
    monkeypatch.setattr(saved, "DEFAULT_BRIEF_EXPECTATIONS", [factual])
    experiment = evaluate_assertion(
        factual, draft, await judge_brief(deepcopy(draft), [factual], "model")
    )
    checks = await saved.grade_saved_section(draft, 1, False, "model")
    rows = claim_rows(draft, checks, sid)
    assert [experiment] == checks
    assert call.await_args_list[0] == call.await_args_list[1]
    assert len(rows) == 2 and rows[0]["quotes_verified"] == "1/1"
    assert rows[1]["verdict"] == "unsupported" and not rows[1]["citations"]
    assert saved.section_result(draft, checks, sid, False)["status"] == "fail"
    content["sections"] = [content["sections"][1]]
    pairs = judged_passages(
        content, [SimpleNamespace(**r) for r in rows], include_uncited=True
    )
    assert len(coverage(content, pairs, include_uncited=True).covered[sid]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_saved_and_experiment_distinguish_failed_evidence_from_a_judge_timeout(
    monkeypatch, timeout
):
    from ui.backend.services import test_runner
    from ui.backend.services.brief_template_evaluation import grade_template_checks

    draft, sid, _ = next(saved.section_inputs(brief_content(), {}))
    factual = next(
        c for c in saved.DEFAULT_BRIEF_EXPECTATIONS if c["type"] == "brief_factual"
    )
    wrong = {
        "claim": 1,
        "factual": True,
        "score": 1,
        "reason": "The log reports it.",
        "unmet": [],
        "supporting_quotes": [{"citation": 1, "quote": "The meter failed."}],
    }
    call = AsyncMock(return_value=(json.dumps({"claims": [wrong]}), {}))
    if timeout:
        call.side_effect = TimeoutError()
    monkeypatch.setattr(test_runner, "_judge_call", call)
    monkeypatch.setattr(saved, "DEFAULT_BRIEF_EXPECTATIONS", [factual])

    async def judge(output, assertions):
        return await judge_brief(output, assertions, "model")

    [experiment] = await grade_template_checks(draft, [factual], judge)
    checks = await saved.grade_saved_section(draft, 0, False, "model")
    [passage] = claim_rows(draft, checks, sid)
    assert checks == [experiment]
    section = saved.section_result(draft, checks, sid, False)
    if timeout:
        assert section["status"] == "error" and checks[0]["error"]
        assert "timed out" in checks[0]["message"]
        assert passage["verdict"] == "cannot_assess"
    else:
        assert section["status"] == "fail" and checks[0]["score"] == 0
        assert "could not be found" in checks[0]["claim_grades"][0]["reason"]
        assert passage["verdict"] == "unsupported"


@pytest.mark.asyncio
async def test_missing_draft_has_nine_ungraded_results_and_no_passages():
    empty, sid, _ = list(saved.section_inputs(brief_content(), {}))[2]
    checks = await saved.grade_saved_section(empty, 2, False, None)
    rows = claim_rows(empty, checks, sid)
    assert not rows and len(checks) == 9 and all(c["not_run"] for c in checks)
    assert saved.section_result(empty, checks, sid, False)["status"] == "error"


def test_changed_evidence_cannot_keep_a_saved_quality_verdict_for_unchanged_words():
    from ui.backend.services.brief_fact_check import current_passages

    original = brief_content()
    judged = [(sid, passage, None) for sid, passage in current_passages(original, True)]
    changed = deepcopy(original)
    changed["sources"][0]["text"] = "A different excerpt."
    assert not coverage(changed, judged, include_uncited=True).covered


def test_same_words_and_shuffled_grades_keep_their_own_reference_and_identity():
    from ui.backend.services.brief_claim_records import bind_claims, claim_passages

    draft, sid, _ = next(saved.section_inputs(brief_content(), {}))
    draft.update(
        summary="Output rose [1]. Output rose [2].",
        sources=[
            dict(index=n, text=f"Recorded in log {n}.", docId=f"d{n}") for n in [1, 2]
        ],
    )
    grades = [
        dict(
            claim=n,
            score=1,
            passed=True,
            reason=f"Log {n}.",
            supporting_quotes=[dict(citation=n, quote=f"log {n}")],
        )
        for n in [2, 1]
    ]
    section = saved.section_result(
        draft, [dict(type="brief_factual", claim_grades=grades)], sid, False
    )
    version = uuid4()
    bind_claims(section, version, 7)
    first, second = [r for _, _, r in claim_passages([section])]
    assert [first["passage"], second["passage"]] == ["Output rose."] * 2
    assert first["id"] != second["id"]
    assert [first["sources"][0]["doc_id"], second["sources"][0]["doc_id"]] == [
        "d1",
        "d2",
    ]
    assert first["explanation"] == "Log 1." and second["explanation"] == "Log 2."
    assert first["passage_id"] == 8 and second["passage_id"] == 9
    assert [r for _, _, r in claim_passages([section], 9)] == [second]
    bind_claims(section, version, 7)
    assert next(claim_passages([section]))[2]["id"] == first["id"]


def test_section_metrics_use_graded_scores_and_explain_an_unavailable_grade():
    checks = [
        dict(type="brief_overlap", applicable=False),
        dict(type="brief_factual", score=0.8),
    ]
    assert (
        saved.section_metrics(dict(status="fail", assertion_results=checks))["score"]
        == 0.8
    )
    checks.append(
        dict(type="brief_length", not_run=True, message="No section text was saved.")
    )
    assert saved.section_metrics(
        dict(status="error", assertion_results=checks)
    ) == dict(score=None, error_message="No section text was saved.")
