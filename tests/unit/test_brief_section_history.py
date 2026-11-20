"""Unit tests for a section's history: Log rows that carry their text, the
change awaiting review (Keep / Reject), and restoring a section version."""

import pytest

from ui.backend.services import brief_citations as bc

pytestmark = pytest.mark.unit


def src(index, chunk, doc="d1"):
    return {
        "chunkId": chunk,
        "docId": doc,
        "title": f"Doc {doc}",
        "text": f"Excerpt {chunk}",
        "score": 0.5,
        "index": index,
    }


def empty_brief(*section_ids):
    return {
        "citationsVersion": 2,
        "title": "B",
        "referenceGrouping": "passage",
        "sources": [],
        "sections": [
            {"id": sid, "title": sid.upper(), "level": 1, "status": "pending"}
            for sid in section_ids
        ],
    }


def generate(content, **extra):
    return {"mode": "generate", "content": content, **extra}


def section(brief, sid):
    return bc.find_section(brief, sid)


def shown(brief, sid):
    return section(brief, sid)["renumbered"]["content"]


class TestLogRowsCarryText:
    def test_generate_row_has_before_after_and_numbering(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("First [1].", sources=[src(1, "c1")]))
        bc.record_run(brief, "a", generate("Second [1].", sources=[src(1, "c2")]))
        first, second = section(brief, "a")["audit"]
        assert (first["before"], first["after"]) == ("", "First [1].")
        assert (second["before"], second["after"]) == ("First [1].", "Second [1].")
        assert second["afterSources"] == {"1": "s2"}

    def test_before_is_the_display_text_not_the_agent_numbers(self):
        brief = empty_brief("a", "b")
        bc.record_run(brief, "a", generate("A [1].", sources=[src(1, "c1")]))
        bc.record_run(brief, "b", generate("B [5].", sources=[src(5, "c9")]))
        bc.record_run(brief, "b", generate("B again [3].", sources=[src(3, "c9")]))
        row = section(brief, "b")["audit"][-1]
        # Readers saw "[2]" (c9 is the brief's second citation), not "[5]".
        assert (row["before"], row["after"]) == ("B [2].", "B again [2].")

    def test_new_run_id_never_reuses_a_logged_id(self):
        brief = empty_brief("a", "b")
        bc.record_run(brief, "a", generate("A [1].", sources=[src(1, "c1")]))
        bc.record_run(brief, "b", generate("B [1].", sources=[src(1, "c2")]))
        # A Log row names r7, whose run is no longer kept (trimmed, or from a
        # restored version): the next run must not take that id.
        section(brief, "a")["audit"].append({"id": "a-r7", "runId": "r7"})
        bc.record_run(brief, "a", generate("A2 [1].", sources=[src(1, "c1")]))
        assert section(brief, "a")["currentRunId"] == "r8"


class TestReview:
    def test_single_section_change_awaits_review_and_keep_ends_it(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("Draft [1].", sources=[src(1, "c1")]))
        bc.record_run(
            brief, "a", generate("Redo [1].", sources=[src(1, "c1")], review=True)
        )
        pending = section(brief, "a")["pendingReview"]
        assert pending["runId"] == "r2" and pending["baseRunId"] == "r1"
        assert pending["before"] == "Draft [1]." and pending["kind"] == "generate"
        with pytest.raises(bc.BriefCitationError):
            bc.keep_review(brief, "a", "r1")
        bc.keep_review(brief, "a", "r2")
        assert "pendingReview" not in section(brief, "a")
        assert shown(brief, "a") == "Redo [1]."

    def test_whole_brief_run_does_not_await_review(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("Draft [1].", sources=[src(1, "c1")]))
        bc.record_run(brief, "a", generate("Again [1].", sources=[src(1, "c1")]))
        assert "pendingReview" not in section(brief, "a")

    def test_condense_carries_the_review_and_reject_undoes_both(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("Draft [1].", sources=[src(1, "c1")]))
        bc.record_run(
            brief,
            "a",
            generate(
                "A very long redo [1] [2].",
                sources=[src(1, "c1"), src(2, "c2")],
                review=True,
            ),
        )
        bc.record_run(brief, "a", {"mode": "condense", "content": "Short [1] [2]."})
        pending = section(brief, "a")["pendingReview"]
        assert pending["runId"] == "r3" and pending["baseRunId"] == "r1"
        bc.reject_run(brief, "a", "r3")
        sec = section(brief, "a")
        assert sec["currentRunId"] == "r1" and shown(brief, "a") == "Draft [1]."
        assert [r["status"] for r in sec["runs"]] == ["current", "rejected", "rejected"]
        assert [a.get("status") for a in sec["audit"]] == [None, "rejected", "rejected"]
        assert brief["references"][0]["sourceId"] == "s1"

    def test_a_later_change_ends_the_review(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("Draft [1].", sources=[src(1, "c1")]))
        bc.record_run(
            brief, "a", generate("Redo [1].", sources=[src(1, "c1")], review=True)
        )
        bc.record_run(brief, "a", {"mode": "manual", "content": "Typed [1]."})
        assert "pendingReview" not in section(brief, "a")
        with pytest.raises(bc.BriefCitationError):
            bc.reject_run(brief, "a", "r2")

    def test_retention_keeps_the_run_reject_returns_to(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("Base [1].", sources=[src(1, "c0")]))
        bc.record_run(
            brief, "a", generate("Redo [1].", sources=[src(1, "c1")], review=True)
        )
        for i in range(2, 8):
            bc.record_run(
                brief, "a", {"mode": "condense", "content": f"Short {i} [1]."}
            )
        sec = section(brief, "a")
        assert sec["pendingReview"]["baseRunId"] == "r1"
        assert "r1" in [r["id"] for r in sec["runs"]]
        bc.reject_run(brief, "a", sec["currentRunId"])
        assert shown(brief, "a") == "Base [1]."


class TestAnnotatedLog:
    def test_read_model_marks_current_and_restorable_rows(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("One [1].", sources=[src(1, "c1")]))
        bc.record_run(
            brief, "a", generate("Two [1].", sources=[src(1, "c2")], review=True)
        )
        bc.reject_run(brief, "a", "r2")
        rows = bc.expand_for_read(brief)["sections"][0]["audit"]
        assert [(r["current"], r["restorable"]) for r in rows] == [
            (True, False),
            (False, True),
        ]

    def test_legacy_row_without_numbering_restores_only_while_its_run_is_kept(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("One [1].", sources=[src(1, "c1")]))
        bc.record_run(brief, "a", generate("Two [1].", sources=[src(1, "c2")]))
        sec = section(brief, "a")
        legacy = sec["audit"][0]
        del legacy["afterSources"]
        assert bc.restorable_text(brief, sec, legacy)[0] == "One [1]."
        sec["runs"] = [r for r in sec["runs"] if r["id"] != "r1"]
        assert bc.restorable_text(brief, sec, legacy) is None


class TestRestoreSectionVersion:
    def test_restore_records_a_new_run_with_the_old_text_and_sources(self):
        brief = empty_brief("a", "b")
        bc.record_run(brief, "a", generate("A [1].", sources=[src(1, "c1")]))
        bc.record_run(brief, "b", generate("B old [1].", sources=[src(1, "c2")]))
        bc.record_run(brief, "b", generate("B new [1].", sources=[src(1, "c3")]))
        old_row = section(brief, "b")["audit"][0]["id"]
        bc.restore_section_version(brief, "b", old_row)
        sec = section(brief, "b")
        assert shown(brief, "b") == "B old [2]."
        restored = sec["runs"][-1]
        assert restored["mode"] == "restore"
        assert restored["mapping"] == {"2": "s2"}
        assert restored["sources"][0]["text"] == "Excerpt c2"
        row = sec["audit"][-1]
        assert row["kind"] == "restore" and row["restoredFrom"]["entryId"] == old_row
        assert (row["before"], row["after"]) == ("B new [2].", "B old [2].")
        assert [r["sourceId"] for r in brief["references"]] == ["s1", "s2"]

    def test_restore_works_after_the_run_is_trimmed_away(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("Oldest [1].", sources=[src(1, "c1")]))
        for i in range(2, 9):
            bc.record_run(
                brief, "a", generate(f"Run {i} [1].", sources=[src(1, f"c{i}")])
            )
        sec = section(brief, "a")
        assert "r1" not in [r["id"] for r in sec["runs"]]
        bc.restore_section_version(brief, "a", "a-r1")
        assert shown(brief, "a") == "Oldest [1]."
        assert brief["references"][0]["sourceId"] == "s1"

    def test_restoring_the_current_row_or_an_unknown_row_is_refused(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("One [1].", sources=[src(1, "c1")]))
        with pytest.raises(bc.BriefCitationError, match="already"):
            bc.restore_section_version(brief, "a", "a-r1")
        with pytest.raises(bc.BriefCitationError, match="Unknown"):
            bc.restore_section_version(brief, "a", "a-r99")

    def test_browser_cannot_record_a_restore_run(self):
        brief = empty_brief("a")
        with pytest.raises(bc.BriefCitationError):
            bc.apply_op(
                brief,
                {
                    "type": "run",
                    "sectionId": "a",
                    "run": generate("x") | {"mode": "restore"},
                },
            )

    def test_keep_through_the_browser_held_operation(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", generate("One [1].", sources=[src(1, "c1")]))
        bc.apply_op(
            brief,
            {
                "type": "run",
                "sectionId": "a",
                "run": generate("Two [1].", sources=[src(1, "c1")], review=True),
            },
        )
        bc.apply_op(brief, {"type": "keep", "sectionId": "a", "runId": "r2"})
        assert "pendingReview" not in section(brief, "a")
