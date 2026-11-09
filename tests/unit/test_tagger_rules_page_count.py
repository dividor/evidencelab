"""Regression test: annex boundary must not swallow the report when page_count is missing."""

from pipeline.processors.tagging.tagger_rules import (
    apply_keyword_locking,
    apply_sequence_rules,
    propagate_hierarchy,
)
from pipeline.processors.tagging.tagger_toc import parse_toc

TOC = """[H1] Table of Contents for Evaluation Report and Annexes | page 2
[H1] Table of Contents for Annexes | page 3
[H2] ANNEX I. Evaluation method | page 3
[H2] ANNEX II. Detailed evaluation findings | page 3
[H1] ACRONYMS AND ABBREVIATIONS | page 5
[H1] EXECUTIVE SUMMARY | page 12
[H1] I. About the programme | page 14
[H1] IV. Overview of findings | page 22
[H1] VI. Recommendations for the outcome areas | page 38
[H1] ANNEX I. EVALUATION METHOD | page 48
[H1] ANNEX II. DETAILED EVALUATION RESULTS | page 52
"""


def _label(document):
    entries = parse_toc(TOC)
    labels = propagate_hierarchy(entries, apply_keyword_locking(entries))
    labels = apply_sequence_rules(entries=entries, labels=labels, document=document)
    return {e["title"]: labels[e["index"]] for e in entries}


def test_report_body_is_not_labelled_annexes_without_page_count():
    labels = _label({})
    assert labels["EXECUTIVE SUMMARY"] == "executive_summary"
    assert labels["VI. Recommendations for the outcome areas"] == "recommendations"
    assert labels["ANNEX II. DETAILED EVALUATION RESULTS"] == "annexes"


def test_result_is_unchanged_when_page_count_is_known():
    assert _label({"page_count": 134}) == _label({})
