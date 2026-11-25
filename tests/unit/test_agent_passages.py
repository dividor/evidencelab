"""Tests for ui/backend/services/agent_passages.py: the research agent's copy of
a search result loses numbers it could cite by mistake, and keeps the rest."""

import pytest

from ui.backend.services.agent_passages import passage_for_agent

pytestmark = pytest.mark.unit


class TestParagraphNumbers:
    """Paragraph numbers were cited as result numbers (18 of 20 citations with
    no source on one measured brief)."""

    def test_removed_after_a_heading_breadcrumb(self):
        text = (
            "-- School meal programme --  143. At the school level, challenges relate"
        )
        assert passage_for_agent(text) == (
            "-- School meal programme --  At the school level, challenges relate"
        )

    def test_removed_after_the_previous_sentence(self):
        text = "traders could provide commodities.  163. Key informants suggested that"
        assert passage_for_agent(text) == (
            "traders could provide commodities.  Key informants suggested that"
        )

    def test_removed_at_the_start_of_the_text_or_a_line(self):
        assert passage_for_agent("90. The evaluation found") == "The evaluation found"
        assert (
            passage_for_agent("Findings\n185. Retention rose")
            == "Findings\nRetention rose"
        )

    def test_removed_before_a_quote(self):
        assert (
            passage_for_agent('Results.  22. "Meals helped"')
            == 'Results.  "Meals helped"'
        )


class TestFootnotesAndReferences:
    def test_footnote_markers_removed(self):
        text = "compared with non-MGD schools. [^94]  In Mozambique, monitors"
        assert (
            passage_for_agent(text)
            == "compared with non-MGD schools.  In Mozambique, monitors"
        )

    def test_footnote_definition_keeps_its_text(self):
        assert passage_for_agent("[^94] WFP. 2019d. Decentralized Evaluation.") == (
            " WFP. 2019d. Decentralized Evaluation."
        )

    @pytest.mark.parametrize(
        "text, expected",
        [
            (
                "articulated in the Constitution [12].",
                "articulated in the Constitution.",
            ),
            ("as other studies found [3, 7], meals", "as other studies found, meals"),
            ("several reviews [4-6] agree", "several reviews agree"),
            ("several reviews [4–6] agree", "several reviews agree"),
        ],
    )
    def test_bracketed_references_removed(self, text, expected):
        assert passage_for_agent(text) == expected


class TestKeepsOtherNumbers:
    """Numbers that carry meaning, or can't be read as a citation, stay."""

    @pytest.mark.parametrize(
        "text",
        [
            "retention increased from 97 percent in 2013. The target was 85 percent",
            "as shown in Table 3. Results by district",
            "Figure 12. Enrolment by year",
            "costs rose by 12.5 percent in 2015",
            "-- 2.3. EVALUATION QUESTION 3 --",
            "ICSP 163 Rutshuru: 73 Beni: 50",
            "see [the annex](https://example.org/annex) for details",
            "a. Baseline retention rates are not available",
        ],
    )
    def test_unchanged(self, text):
        assert passage_for_agent(text) == text

    def test_empty_text(self):
        assert passage_for_agent("") == ""
