"""The provider smoke test grades the same word targets as saved Briefs."""

import pytest

from tests.integration import demo_smoke_test as demo

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("words", "target", "passes"),
    [(153, 150, True), (263, 250, True), (60, 150, False), (175, 150, False)],
)
def test_demo_section_grades_word_target_without_masking_other_checks(
    monkeypatch, words, target, passes
):
    events = [
        {"type": "phase", "phase": "checking_citations"},
        {"type": "token", "token": "Finding " * words + "[1]"},
        {"type": "sources", "sources": [{"index": 1, "chunkId": "passage"}]},
        {"type": "done", "section_written": True},
    ]
    results = {}
    monkeypatch.setattr(demo, "_research_events", lambda *args, **kwargs: events)
    monkeypatch.setattr(
        demo, "check", lambda name, success, *detail: results.update({name: success})
    )
    demo._check_brief_section({}, {}, "Methods", target, {})
    assert results == {
        "Methods produced reviewed prose without extra headings": True,
        "Methods meets the Brief word target": passes,
        "Methods cites real sources": True,
    }
