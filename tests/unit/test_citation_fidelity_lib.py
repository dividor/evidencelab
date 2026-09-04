"""Unit tests for notebooks/citation_fidelity_lib.py.

The module ports citation logic from the frontend
(CitedContent.tsx, briefHighlights.ts); these tests pin the ported behaviour
to the same cases the frontend relies on.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "notebooks"))

from citation_fidelity_lib import (  # noqa: E402
    build_faithfulness_input,
    cited_context_texts,
    extract_citation_pairs,
    extract_cited_numbers,
    find_claim_match,
    normalize_claim_text,
    normalize_ws,
    parse_section_breadcrumb,
    sentences_citing,
    split_sentences,
    strip_citation_markers,
)


@pytest.mark.unit
class TestExtractCitedNumbers:
    def test_extract_cited_numbers_when_single_and_grouped_then_sorted_unique(self):
        text = "One fact [3]. Another [1, 3]. More [12]."
        assert extract_cited_numbers(text) == [1, 3, 12]

    def test_extract_cited_numbers_when_no_markers_then_empty(self):
        assert extract_cited_numbers("No citations here.") == []

    def test_extract_cited_numbers_when_bracketed_words_then_ignored(self):
        assert extract_cited_numbers("See [appendix] and [1a].") == []


@pytest.mark.unit
class TestNormalizeClaimText:
    def test_normalize_claim_text_when_markers_and_markdown_then_stripped(self):
        raw = "**School feeding** improved  attendance [26, 21]."
        assert normalize_claim_text(raw) == "school feeding improved attendance ."

    def test_normalize_claim_text_when_heading_chars_then_removed(self):
        assert normalize_claim_text("## A `code` > quote_") == "a code quote"


@pytest.mark.unit
class TestParseSectionBreadcrumb:
    def test_parse_section_breadcrumb_when_leading_marker_line_then_split(self):
        text = "-- 3. Conclusions > 3.1 --\n\n227. School Feeding. Body text."
        section, body = parse_section_breadcrumb(text)
        assert section == "3. Conclusions > 3.1"
        assert body == "227. School Feeding. Body text."

    def test_parse_section_breadcrumb_when_no_marker_then_body_unchanged(self):
        section, body = parse_section_breadcrumb("Plain chunk text.")
        assert section is None
        assert body == "Plain chunk text."

    def test_parse_section_breadcrumb_when_blank_lines_first_then_still_found(self):
        section, body = parse_section_breadcrumb("\n\n-- Heading --\nBody.")
        assert section == "Heading"
        assert body == "Body."


@pytest.mark.unit
class TestSentencesCiting:
    def test_sentences_citing_when_index_in_group_then_found(self):
        markdown = "Fact A [1, 3]. Fact B [2].\nFact C [3]."
        assert sentences_citing(markdown, 3) == ["Fact A [1, 3].", "Fact C [3]."]

    def test_sentences_citing_when_index_is_substring_then_not_matched(self):
        # [145] must not match source 45 (and vice versa).
        markdown = "Fact [145]."
        assert sentences_citing(markdown, 45) == []
        assert sentences_citing(markdown, 145) == ["Fact [145]."]

    def test_split_sentences_when_newlines_then_break_sentences(self):
        assert split_sentences("## Head\nOne. Two!") == ["## Head", "One.", "Two!"]


@pytest.mark.unit
class TestFindClaimMatch:
    def test_find_claim_match_when_exact_key_then_returned(self):
        source = {
            "claimMatches": [{"claim": "fact a .", "matches": [{"start": 0, "end": 5}]}]
        }
        assert find_claim_match(source, "Fact A [1].") is source["claimMatches"][0]

    def test_find_claim_match_when_long_key_containment_then_returned(self):
        claim = "a fairly long claim sentence about school feeding ."
        source = {"claimMatches": [{"claim": claim, "matches": []}]}
        sentence = "Also, " + claim.capitalize()
        assert find_claim_match(source, sentence) is source["claimMatches"][0]

    def test_find_claim_match_when_short_key_containment_then_not_matched(self):
        source = {"claimMatches": [{"claim": "short claim .", "matches": []}]}
        assert find_claim_match(source, "Longer: short claim.") is None


@pytest.mark.unit
class TestExtractCitationPairs:
    def _section(self):
        return {
            "title": "S",
            "status": "done",
            "content": "Fact A [1]. Fact B [2]. Broken [9].",
            "sources": [
                {
                    "index": 1,
                    "chunkId": "c1",
                    "text": "-- H --\n\nSupporting body for fact A.",
                    "claimMatches": [
                        {
                            "claim": "fact a .",
                            "matches": [{"start": 0, "end": 10}],
                        }
                    ],
                },
                {"index": 2, "chunkId": "c2", "text": "Body two."},
            ],
        }

    def test_extract_citation_pairs_when_marker_has_source_then_resolved(self):
        pairs = extract_citation_pairs(self._section())
        assert [(p.citation_index, p.dangling) for p in pairs] == [
            (1, False),
            (2, False),
            (9, True),
        ]

    def test_extract_citation_pairs_when_claim_match_stored_then_span_text_extracted(
        self,
    ):
        pair = extract_citation_pairs(self._section())[0]
        assert pair.has_stored_support
        # Offsets are relative to the body after the breadcrumb line.
        assert pair.matched_texts == ["Supporting"]

    def test_extract_citation_pairs_when_no_claim_match_then_no_support(self):
        pair = extract_citation_pairs(self._section())[1]
        assert not pair.has_stored_support
        assert pair.matched_texts == []


@pytest.mark.unit
class TestNormalizeWs:
    def test_normalize_ws_when_mixed_whitespace_then_collapsed(self):
        assert normalize_ws("a\n b\t\tc ") == "a b c"


@pytest.mark.unit
class TestStripCitationMarkers:
    def test_strip_citation_markers_when_markers_present_then_removed_cleanly(self):
        text = "Fact A [1]. Fact B [26, 21], and more [3]."
        assert strip_citation_markers(text) == "Fact A. Fact B, and more."

    def test_strip_citation_markers_when_no_markers_then_unchanged(self):
        assert strip_citation_markers("Plain text.") == "Plain text."

    def test_strip_citation_markers_when_newlines_then_preserved(self):
        assert strip_citation_markers("## Head\nFact [1].") == "## Head\nFact."


@pytest.mark.unit
class TestCitedContextTexts:
    def _section(self):
        return {
            "content": "Fact A [1]. Fact B [1, 3].",
            "sources": [
                {"index": 1, "chunkId": "c1", "text": "Chunk one."},
                {"index": 2, "chunkId": "c2", "text": "Uncited chunk."},
                {"index": 3, "chunkId": "c1", "text": "Chunk one."},
                {"index": 4, "chunkId": "c4", "text": ""},
            ],
        }

    def test_cited_context_texts_when_cited_then_included_in_order(self):
        assert cited_context_texts(self._section()) == ["Chunk one."]

    def test_cited_context_texts_when_uncited_or_empty_then_excluded(self):
        contexts = cited_context_texts(self._section())
        assert "Uncited chunk." not in contexts
        assert "" not in contexts


@pytest.mark.unit
class TestBuildFaithfulnessInput:
    def test_build_faithfulness_input_when_section_given_then_sample_shaped(self):
        section = {
            "title": "Outcomes",
            "content": "Fact A [1].",
            "sources": [{"index": 1, "chunkId": "c1", "text": "Chunk one."}],
        }
        sample = build_faithfulness_input("School feeding", section)
        assert sample == {
            "user_input": "School feeding — Outcomes",
            "response": "Fact A.",
            "retrieved_contexts": ["Chunk one."],
        }
