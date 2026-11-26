import pytest

from ui.backend.services.assistant_grounding import (
    CitationCheck,
    EvidenceQuote,
    citation_issues,
    numbered_sentences,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("label", [7, "[7]", [7]])
def test_grounding_accepts_equivalent_single_citation_labels(label):
    quote = EvidenceQuote(citation=label, quote="received the meal")
    assert quote.citation == 7


def test_grounding_requires_a_real_quote_from_every_source_named_in_a_sentence():
    sentences = numbered_sentences("The pilot reached more schools in 2023 [1, 2].")
    evidence = {
        1: "The pilot reached 50 schools in 2023.",
        2: "The project opened in 2022.",
    }
    response = CitationCheck.model_validate(
        {
            "scope_issues": [],
            "sentences": [
                {
                    "id": 1,
                    "status": "supported",
                    "quotes": [
                        {"citation": 1, "quote": "reached 50 schools"},
                        {"citation": 2, "quote": "reached 50 schools"},
                    ],
                }
            ],
        }
    )
    assert citation_issues(sentences, evidence, response) == (
        [
            "Sentence 1 lacks verified quotes from [2].",
        ],
        set(),
    )


def test_grounding_requires_the_judge_to_return_every_sentence():
    sentences = numbered_sentences("A cited finding [1]. An invented conclusion.")
    response = CitationCheck.model_validate({"scope_issues": [], "sentences": []})
    assert citation_issues(sentences, {}, response) == (
        [
            "The citation checker did not assess each sentence exactly once.",
        ],
        set(),
    )


def test_grounding_rejects_uncited_facts_and_accepts_a_qualified_evidence_gap():
    sentences = numbered_sentences(
        "The programme doubled enrolment. The reports reviewed did not estimate national coverage."
    )
    response = CitationCheck.model_validate(
        {
            "scope_issues": [],
            "sentences": [
                {"id": 1, "status": "supported"},
                {"id": 2, "status": "evidence_gap"},
            ],
        }
    )
    assert citation_issues(sentences, {}, response) == (
        [
            "Sentence 1: Factual content lacks citation support.",
        ],
        {2},
    )
