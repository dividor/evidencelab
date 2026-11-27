import pytest

from ui.backend.services.assistant_grounding import (
    CitationCheck,
    EvidenceQuote,
    citation_check_batches,
    citation_issues,
    numbered_sentences,
)

pytestmark = pytest.mark.unit


def test_citation_batches_limit_the_work_per_verdict_without_dropping_claims():
    sentences = numbered_sentences(
        "A finding [1, 2, 3, 4]. A second finding [5, 6, 7]. "
        "A third finding [8]. A fourth finding [9]. A fifth finding [10]. "
        "A sixth finding [11]."
    )

    batches = list(citation_check_batches(sentences))

    assert [[row["id"] for row in batch] for batch in batches] == [
        [1],
        [2, 3, 4, 5],
        [6],
    ]
    assert [row for batch in batches for row in batch] == sentences


def test_check_batch_keeps_the_comparison_from_the_previous_paragraph_or_draft():
    previous = "The first site ran more slowly after the upgrade [14]."
    draft = (
        "The other sites recovered at different rates [1, 2, 3, 4, 5, 6].\n\n"
        "The report attributed this difference to staffing [7]."
    )
    first, second = citation_check_batches(numbered_sentences(draft, previous))
    assert first[0]["preceding_sentence"] == previous
    assert second[0]["preceding_sentence"] == first[0]["text"]
    assert second[0]["citations"] == [7]


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
