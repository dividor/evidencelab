"""Unit tests for the Python citation/reference rendering.

This module (``ui.backend.services.citations``) is the server-side mirror of the
frontend ``citations.ts`` / ``AiSummaryReferences.tsx`` logic. These tests pin
the behaviour the search UI has — grouping citations by document and appending
each citation's page number — so the evaluation harness stays in lock-step.
"""

import pytest

from ui.backend.services.citations import group_references, render_reference_lines

pytestmark = [pytest.mark.unit]


def test_group_references_groups_by_document_in_first_cited_order():
    references = [
        {"number": 1, "title": "Doc A", "page_num": 5},
        {"number": 2, "title": "Doc B", "page_num": 3},
        {"number": 3, "title": "Doc A", "page_num": 12},
    ]
    groups = group_references(references)
    assert [g["title"] for g in groups] == ["Doc A", "Doc B"]
    # Doc A collapses its two citations into one group, preserving page numbers.
    assert groups[0]["refs"] == [
        {"number": 1, "page_num": 5},
        {"number": 3, "page_num": 12},
    ]
    assert groups[1]["refs"] == [{"number": 2, "page_num": 3}]


def test_group_references_falls_back_to_doc_id_then_unknown():
    groups = group_references(
        [
            {"number": 1, "doc_id": "d1"},
            {"number": 2},
        ]
    )
    assert [g["title"] for g in groups] == ["d1", "Unknown"]


def test_render_reference_lines_includes_metadata_and_pages():
    lines = render_reference_lines(
        [
            {
                "number": 1,
                "title": "Kenya SMP",
                "organization": "WFP",
                "year": 2018,
                "page_num": 12,
            }
        ]
    )
    assert lines == ["Kenya SMP, WFP, 2018 | [1] p.12"]


def test_render_reference_lines_shows_page_range_per_document():
    lines = render_reference_lines(
        [
            {"number": 1, "title": "Kenya SMP", "organization": "WFP", "page_num": 5},
            {"number": 3, "title": "Kenya SMP", "organization": "WFP", "page_num": 12},
        ]
    )
    assert lines == ["Kenya SMP, WFP | [1] p.5 [3] p.12"]


def test_render_reference_lines_omits_page_when_falsy():
    # A missing page or an unknown page of 0 renders no ``p.`` suffix, matching
    # the frontend's truthiness check.
    lines = render_reference_lines(
        [
            {"number": 1, "title": "No Page"},
            {"number": 2, "title": "Zero Page", "page_num": 0},
        ]
    )
    assert lines == ["No Page | [1]", "Zero Page | [2]"]


def test_render_reference_lines_empty_when_no_references():
    assert render_reference_lines([]) == []
