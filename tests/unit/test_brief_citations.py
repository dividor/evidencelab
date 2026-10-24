"""Unit tests for the brief citation mapping and renumbering service."""

import copy
import json

import pytest

from ui.backend.services import brief_citations as bc

pytestmark = pytest.mark.unit


def src(index, chunk, doc="d1", page=None, text=None, title=None):
    """An agent source record as the deep-research stream emits it."""
    return {
        "chunkId": chunk,
        "docId": doc,
        "title": title or f"Doc {doc}",
        "text": text or f"Excerpt of {chunk}",
        "score": 0.5,
        "page": page,
        "index": index,
        "headings": [],
    }


def empty_brief(*section_ids):
    return {
        "citationsVersion": 2,
        "title": "Brief",
        "referenceGrouping": "passage",
        "sources": [],
        "sections": [
            {"id": sid, "title": f"Section {sid}", "level": 1, "status": "pending"}
            for sid in section_ids
        ],
    }


def run(content, sources, mode="generate", **extra):
    return {"mode": mode, "content": content, "sources": sources, **extra}


def display_content(brief, section_id):
    return bc.find_section(brief, section_id)["renumbered"]["content"]


def references(brief):
    return [(r["n"], r["sourceId"], r["page"]) for r in brief["references"]]


# ---------------------------------------------------------------------------
# Originals
# ---------------------------------------------------------------------------


class TestOriginal:
    def test_original_stored_unchanged_and_survives_later_changes(self):
        brief = empty_brief("a", "b")
        sources = [src(1, "c1", page=4), src(2, "c2", page=9)]
        text = "# Section a\n\nA claim [2]. Another [1]."
        bc.record_run(brief, "a", run(text, sources), now_ms=1)
        original = copy.deepcopy(bc.find_section(brief, "a")["runs"][0])
        assert original["content"] == text
        assert original["sources"] == sources

        bc.record_run(brief, "b", run("B cites [1].", [src(1, "c2")]), now_ms=2)
        bc.set_grouping(brief, "document-single", now_ms=3)
        bc.apply_structure(
            brief,
            {"sections": [{"id": "b", "title": "B first"}, {"id": "a", "title": "A"}]},
            now_ms=4,
        )
        bc.set_highlights(brief, {"s1": [{"claim": "x", "matches": []}]})
        assert bc.find_section(brief, "a")["runs"][0] == original
        # The display text was derived; the original kept its own numbers.
        assert "[2]" in original["content"]
        assert display_content(brief, "a").startswith("A claim [")

    def test_run_summary_omits_content_and_sources(self):
        brief = empty_brief("a")
        bc.record_run(
            brief, "a", run("Text [1].", [src(1, "c1")], runId="abc"), now_ms=1
        )
        read = bc.expand_for_read(brief)
        summary = read["sections"][0]["runs"][0]
        assert "content" not in summary and "sources" not in summary
        assert summary["runId"] == "abc"
        assert summary["sourceCount"] == 1 and summary["citedCount"] == 1
        assert summary["mapping"] == {"1": "s1"}
        assert "sources" not in read  # the brief-wide list is not returned

    def test_run_detail_returns_the_original_and_display_numbers(self):
        brief = empty_brief("a", "b")
        bc.record_run(brief, "a", run("A [1].", [src(1, "c1")]), now_ms=1)
        bc.record_run(
            brief, "b", run("B [1] and [2].", [src(1, "c2"), src(2, "c1")]), now_ms=2
        )
        detail = bc.run_detail(brief, "b", "r2")
        assert detail["content"] == "B [1] and [2]."
        assert detail["displayNumbers"] == {"1": 2, "2": 1}

    def test_legacy_content_is_refused(self):
        legacy = {"sections": [{"content": "x [1]", "sources": [src(1, "c1")]}]}
        with pytest.raises(bc.LegacyBriefError):
            bc.renumber(legacy)
        with pytest.raises(bc.LegacyBriefError):
            bc.record_run(legacy, "a", run("x", []))


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------


class TestNumbering:
    def test_same_chunk_cited_from_two_sections_gets_one_number(self):
        brief = empty_brief("a", "b")
        bc.record_run(
            brief, "a", run("First [1]. Second [2].", [src(1, "c1"), src(2, "c2")])
        )
        bc.record_run(
            brief, "b", run("Again [1]. New [2].", [src(1, "c1"), src(2, "c3")])
        )
        assert display_content(brief, "a") == "First [1]. Second [2]."
        assert display_content(brief, "b") == "Again [1]. New [3]."
        assert references(brief) == [(1, "s1", None), (2, "s2", None), (3, "s3", None)]
        assert len(brief["sources"]) == 3

    def test_same_agent_number_in_two_sections_means_two_numbers(self):
        brief = empty_brief("a", "b")
        bc.record_run(brief, "a", run("A [1].", [src(1, "c1")]))
        bc.record_run(brief, "b", run("B [1].", [src(1, "c2")]))
        assert display_content(brief, "b") == "B [2]."
        assert [r["sourceId"] for r in brief["references"]] == ["s1", "s2"]

    def test_numbers_follow_reading_order_not_agent_order(self):
        brief = empty_brief("a")
        bc.record_run(
            brief, "a", run("Late [3]. Early [1].", [src(1, "c1"), src(3, "c3")])
        )
        assert display_content(brief, "a") == "Late [1]. Early [2]."

    def test_combined_marker_is_rewritten_and_deduplicated(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", run("Claim [2, 1, 2].", [src(1, "c1"), src(2, "c2")]))
        assert display_content(brief, "a") == "Claim [1, 2]."

    def test_section_order_renumbers_and_a_save_cannot_hide_a_researched_section(self):
        brief = empty_brief("a", "b")
        bc.record_run(brief, "a", run("A [1].", [src(1, "c1")]))
        bc.record_run(brief, "b", run("B [1].", [src(1, "c2")]))
        # The client's snapshot says "a" is pending (a save racing a research
        # run, or a regenerate in progress): the stored run keeps it done.
        bc.apply_structure(
            brief, {"sections": [{"id": "b"}, {"id": "a", "status": "pending"}]}
        )
        assert display_content(brief, "b") == "B [1]."
        assert display_content(brief, "a") == "A [2]."
        assert bc.find_section(brief, "a")["status"] == "done"
        assert references(brief) == [(1, "s2", None), (2, "s1", None)]
        # And a section with no run is pending whatever the client says.
        bc.apply_structure(
            brief,
            {"sections": [{"id": "a"}, {"id": "c", "title": "C", "status": "done"}]},
        )
        assert bc.find_section(brief, "c")["status"] == "pending"
        assert references(brief) == [(1, "s1", None)]

    def test_leading_title_stripped_and_adjacent_duplicates_collapsed(self):
        brief = empty_brief("a")
        bc.find_section(brief, "a")["title"] = "Findings"
        bc.record_run(
            brief,
            "a",
            run("## Findings\n\nOne [1][1]. Two [1] [1].", [src(1, "c1")]),
        )
        assert display_content(brief, "a") == "One [1]. Two [1]."

    def test_source_count_is_every_registered_record(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", run("Only [1].", [src(1, "c1"), src(2, "c2")]))
        assert brief["sourceCount"] == 2
        assert (
            bc.expand_for_read(brief)["sections"][0]["renumbered"]["sources"][0][
                "chunkId"
            ]
            == "c1"
        )


class TestUnresolvedAndRejected:
    def test_unresolved_marker_is_recorded_and_kept_visible(self):
        brief = empty_brief("a")
        bc.record_run(
            brief, "a", run("Fine [1]. Lost [7]. Mixed [1, 7].", [src(1, "c1")])
        )
        section = bc.find_section(brief, "a")
        assert section["runs"][0]["unresolved"] == [{"n": 7, "reason": "no-source"}]
        assert section["renumbered"]["unresolved"] == [{"n": 7, "reason": "no-source"}]
        assert section["audit"][0]["unresolvedCount"] == 1
        assert display_content(brief, "a") == "Fine [1]. Lost [?7]. Mixed [1][?7]."
        assert bc.CITATION_RE.search("[?7]") is None

    def test_source_without_chunk_id_is_rejected_not_merged(self):
        brief = empty_brief("a")
        no_chunk = {**src(2, "", doc="d9", page=3), "chunkId": ""}
        bc.record_run(brief, "a", run("Ok [1]. Bad [2].", [src(1, "c1"), no_chunk]))
        section = bc.find_section(brief, "a")
        assert [s["chunkId"] for s in brief["sources"]] == ["c1"]
        assert section["runs"][0]["rejected"] == [{"index": 2, "reason": "no-chunk-id"}]
        assert section["runs"][0]["unresolved"] == [{"n": 2, "reason": "no-chunk-id"}]
        assert display_content(brief, "a") == "Ok [1]. Bad [?2]."
        assert not any(s.get("page") == 3 for s in brief["sources"])

    def test_unresolved_markers_appear_in_display_sections(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", run("Lost [7].", []))
        sections = bc.display_sections(brief)
        assert sections[0]["content"] == "Lost [?7]."
        assert sections[0]["unresolved"] == [{"n": 7, "reason": "no-source"}]


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


class TestGrouping:
    def _two_pages(self):
        brief = empty_brief("a", "b")
        bc.record_run(
            brief,
            "a",
            run(
                "P32 [1]. P56 [2]. Other [3].",
                [
                    src(1, "c1", page=32),
                    src(2, "c2", page=56),
                    src(3, "c3", doc="d2", page=4),
                ],
            ),
        )
        bc.record_run(brief, "b", run("Back to p56 [1].", [src(1, "c2", page=56)]))
        return brief

    def test_per_passage_numbers_each_chunk_with_its_page(self):
        brief = self._two_pages()
        assert display_content(brief, "a") == "P32 [1]. P56 [2]. Other [3]."
        assert display_content(brief, "b") == "Back to p56 [2]."
        assert references(brief) == [(1, "s1", 32), (2, "s2", 56), (3, "s3", 4)]
        assert [g["title"] for g in brief["referenceGroups"]] == ["Doc d1", "Doc d2"]
        assert [c["n"] for c in brief["referenceGroups"][0]["cites"]] == [1, 2]

    def test_per_document_single_shares_one_number_without_pages(self):
        brief = self._two_pages()
        bc.set_grouping(brief, "document-single")
        assert display_content(brief, "a") == "P32 [1]. P56 [1]. Other [2]."
        assert display_content(brief, "b") == "Back to p56 [1]."
        assert references(brief) == [(1, "s1", None), (2, "s3", None)]
        row = bc.find_section(brief, "a")["renumbered"]["sources"][0]
        assert row == {"index": 1, "sourceId": "s1", "variantIds": ["s2"]}
        expanded = bc.expand_for_read(brief)["sections"][0]["renumbered"]["sources"][0]
        assert [v["chunkId"] for v in expanded["variants"]] == ["c2"]

    def test_grouping_change_rewrites_stored_renumbered_version(self):
        brief = self._two_pages()
        before = copy.deepcopy(bc.find_section(brief, "a")["renumbered"])
        bc.set_grouping(brief, "document-single", now_ms=99)
        after = bc.find_section(brief, "a")["renumbered"]
        assert after["grouping"] == "document-single"
        assert after["computedAt"] == 99
        assert after["content"] != before["content"]
        bc.set_grouping(brief, "passage")
        assert bc.find_section(brief, "a")["renumbered"]["content"] == before["content"]

    def test_document_multiple_numbers_like_passage(self):
        brief = self._two_pages()
        passage = display_content(brief, "a")
        bc.set_grouping(brief, "document-multiple")
        assert display_content(brief, "a") == passage

    def test_unknown_grouping_rejected(self):
        with pytest.raises(bc.BriefCitationError):
            bc.set_grouping(empty_brief("a"), "by-colour")


# ---------------------------------------------------------------------------
# Stability of ids across regenerate / reorder / delete
# ---------------------------------------------------------------------------


class TestStability:
    def _brief(self):
        brief = empty_brief("a", "b", "c")
        bc.record_run(brief, "a", run("A [1].", [src(1, "c1")]))
        bc.record_run(brief, "b", run("B [1] [2].", [src(1, "c2"), src(2, "c1")]))
        bc.record_run(brief, "c", run("C [1].", [src(1, "c3")]))
        return brief

    def test_regenerating_one_section_keeps_other_ids(self):
        brief = self._brief()
        bc.record_run(brief, "a", run("A again [1] [2].", [src(1, "c9"), src(2, "c1")]))
        ids = {s["chunkId"]: s["id"] for s in brief["sources"]}
        assert ids["c1"] == "s1" and ids["c2"] == "s2" and ids["c3"] == "s3"
        assert ids["c9"] == "s4"
        # b still cites s2 and s1; c still cites s3.
        b_rows = bc.find_section(brief, "b")["renumbered"]["sources"]
        assert [r["sourceId"] for r in b_rows] == ["s2", "s1"]

    def test_reordering_changes_numbers_but_not_ids(self):
        brief = self._brief()
        bc.apply_structure(brief, {"sections": [{"id": "c"}, {"id": "b"}, {"id": "a"}]})
        assert display_content(brief, "c") == "C [1]."
        assert display_content(brief, "b") == "B [2] [3]."
        assert display_content(brief, "a") == "A [3]."
        assert [r["sourceId"] for r in brief["references"]] == ["s3", "s2", "s1"]

    def test_deleting_a_section_drops_its_runs_but_keeps_source_ids(self):
        brief = self._brief()
        bc.apply_structure(brief, {"sections": [{"id": "a"}, {"id": "c"}]})
        assert [s["id"] for s in brief["sections"]] == ["a", "c"]
        assert {s["id"] for s in brief["sources"]} == {"s1", "s2", "s3"}
        assert references(brief) == [(1, "s1", None), (2, "s3", None)]

    def test_new_section_with_template_text_gets_a_manual_run(self):
        brief = empty_brief()
        bc.apply_structure(
            brief,
            {
                "sections": [
                    {
                        "id": "t",
                        "title": "T",
                        "status": "done",
                        "content": "Given text.",
                    }
                ]
            },
        )
        section = bc.find_section(brief, "t")
        assert section["runs"][0]["mode"] == "manual"
        assert section["renumbered"]["content"] == "Given text."

    def test_structure_save_cannot_alter_citation_facts(self):
        brief = self._brief()
        tampered = {
            "sections": [{"id": "a", "renumbered": {"content": "hacked"}, "runs": []}],
            "sources": [],
            "references": [{"n": 9}],
        }
        bc.apply_structure(brief, tampered)
        assert display_content(brief, "a") == "A [1]."
        assert len(brief["sources"]) == 3
        assert bc.find_section(brief, "a")["runs"]


# ---------------------------------------------------------------------------
# Revise, reject, retention
# ---------------------------------------------------------------------------


class TestRunsAndRetention:
    def test_edit_inherits_sources_and_records_before_after(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", run("Draft [1].", [src(1, "c1")]), now_ms=1)
        bc.record_run(
            brief,
            "a",
            {"mode": "edit", "content": "Polished [1].", "instruction": "polish"},
            now_ms=2,
        )
        section = bc.find_section(brief, "a")
        # The edit was written against the display numbering, so its sources
        # are the display records numbered as shown; the superseded run is
        # trimmed to its cited records straight away.
        assert [(s["index"], s["chunkId"]) for s in section["runs"][1]["sources"]] == [
            (1, "c1")
        ]
        assert section["runs"][1]["sourcesRetained"] == "exact"
        assert section["runs"][0]["status"] == "superseded"
        assert section["runs"][0]["sourcesRetained"] == "cited-without-excerpt"
        entry = section["audit"][1]
        assert entry["kind"] == "edit" and entry["runId"] == "r2"
        assert (entry["before"], entry["after"]) == ("Draft [1].", "Polished [1].")
        assert display_content(brief, "a") == "Polished [1]."

    def test_revise_run_uses_display_numbering_and_based_on_guard(self):
        brief = empty_brief("a", "b")
        bc.record_run(brief, "a", run("A [1].", [src(1, "c1")]))
        bc.record_run(brief, "b", run("B [4] then [2].", [src(2, "c1"), src(4, "c9")]))
        # On screen section b reads "B [2] then [1]."; a manual edit of that
        # text keeps [2] pointing at c9 and [1] at c1.
        assert bc.display_numbering(bc.find_section(brief, "b")) == {
            "1": "s1",
            "2": "s2",
        }
        bc.record_run(
            brief,
            "b",
            {
                "mode": "manual",
                "content": "B [2] edited, then [1].",
                "basedOn": {"1": "s1", "2": "s2"},
            },
        )
        section = bc.find_section(brief, "b")
        assert [(s["index"], s["chunkId"]) for s in section["runs"][1]["sources"]] == [
            (2, "c9"),
            (1, "c1"),
        ]
        assert display_content(brief, "b") == "B [2] edited, then [1]."
        assert [r["sourceId"] for r in brief["references"]] == ["s1", "s2"]
        with pytest.raises(bc.BriefCitationError):
            bc.record_run(
                brief, "b", {"mode": "manual", "content": "x", "basedOn": {"1": "s2"}}
            )

    def test_reject_restores_previous_run_and_drops_its_audit_row(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", run("Draft [1].", [src(1, "c1")]))
        bc.record_run(
            brief,
            "a",
            {
                "mode": "update",
                "content": "Updated [1] [2].",
                "sources": [src(1, "c1"), src(2, "c2")],
            },
        )
        bc.reject_run(brief, "a", "r2")
        section = bc.find_section(brief, "a")
        assert section["currentRunId"] == "r1"
        assert section["runs"][1]["status"] == "rejected"
        assert [a["runId"] for a in section["audit"]] == ["r1"]
        assert display_content(brief, "a") == "Draft [1]."
        with pytest.raises(bc.BriefCitationError):
            bc.reject_run(brief, "a", "r2")

    def test_reject_only_run_leaves_section_pending(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", run("Draft [1].", [src(1, "c1")]))
        bc.reject_run(brief, "a", "r1")
        section = bc.find_section(brief, "a")
        assert section["status"] == "pending" and section["currentRunId"] is None
        assert brief["references"] == []

    def test_retention_keeps_latest_exact_trims_four_drops_rest(self):
        brief = empty_brief("a")
        for i in range(1, 8):
            bc.record_run(
                brief,
                "a",
                run(
                    f"Run {i} cites [1].",
                    [src(1, f"c{i}", text="long excerpt"), src(2, "uncited")],
                ),
            )
        section = bc.find_section(brief, "a")
        assert [r["id"] for r in section["runs"]] == ["r3", "r4", "r5", "r6", "r7"]
        latest = section["runs"][-1]
        assert latest["sourcesRetained"] == "exact" and len(latest["sources"]) == 2
        older = section["runs"][0]
        assert older["sourcesRetained"] == "cited-without-excerpt"
        assert [s["chunkId"] for s in older["sources"]] == ["c3"]
        assert "text" not in older["sources"][0]
        assert older["content"] == "Run 3 cites [1]."
        assert older["mapping"] == {"1": "s4", "2": "s2"}
        # Every audit row still names its run, retained or not.
        assert [a["runId"] for a in section["audit"]] == [f"r{i}" for i in range(1, 8)]
        with pytest.raises(bc.BriefCitationError):
            bc.run_detail(brief, "a", "r1")

    def test_size_ceiling_is_enforced(self, monkeypatch):
        from ui.backend.services import brief_citation_runs

        monkeypatch.setattr(brief_citation_runs, "MAX_CONTENT_CHARS", 500)
        brief = empty_brief("a")
        with pytest.raises(bc.BriefTooLargeError):
            bc.record_run(brief, "a", run("x [1]", [src(1, "c1", text="y" * 600)]))


# ---------------------------------------------------------------------------
# Trace and anonymous operations
# ---------------------------------------------------------------------------


class TestTrace:
    def test_displayed_number_traces_to_agent_marker_and_source(self):
        brief = empty_brief("a", "b")
        bc.record_run(brief, "a", run("A [1].", [src(1, "c1")]))
        bc.record_run(brief, "b", run("B [5] again [5].", [src(5, "c7", page=12)]))
        t = bc.trace(brief, "b", 2)
        assert t["sourceId"] == "s2" and t["chunkId"] == "c7" and t["page"] == 12
        assert t["agentIndices"] == [5] and t["runId"] == "r2"
        assert t["agentSources"][0]["index"] == 5
        expanded = bc.display_sections(brief)[1]["sources"][0]
        assert expanded["index"] == 2 and expanded["agentIndices"] == [5]
        with pytest.raises(bc.BriefCitationError):
            bc.trace(brief, "b", 9)

    def test_apply_op_mirrors_the_endpoints(self):
        brief = empty_brief("a")
        brief = bc.apply_op(
            brief,
            {"type": "run", "sectionId": "a", "run": run("A [1].", [src(1, "c1")])},
        )
        brief = bc.apply_op(brief, {"type": "grouping", "grouping": "document-single"})
        brief = bc.apply_op(
            brief,
            {
                "type": "highlights",
                "highlights": {"s1": [{"claim": "a", "matches": []}]},
            },
        )
        assert bc.apply_op(brief, {"type": "read"}) is brief
        assert brief["referenceGrouping"] == "document-single"
        assert brief["sources"][0]["claimMatches"] == [{"claim": "a", "matches": []}]
        with pytest.raises(bc.BriefCitationError):
            bc.apply_op(brief, {"type": "explode"})

    def test_read_model_is_json_serialisable(self):
        brief = empty_brief("a")
        bc.record_run(brief, "a", run("A [1].", [src(1, "c1")]))
        json.dumps(bc.expand_for_read(brief))
