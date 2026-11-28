import json

import pytest

from ui.backend.services.assistant_grounding import InvalidAssistantResponse
from ui.backend.services.brief_excerpt_citations import cite_missing_excerpts

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_missing_references_keep_the_supported_opening_in_its_own_paragraph():
    raw = (
        "The probes lost power. Their backup lasted an hour [2].\n\nSamples warmed."
        "\n\nLimit: The duration is unclear."
    )

    async def identify(system, prompt, history, config, schema):
        assert "Their backup lasted an hour" in prompt
        assert "Battery log" in prompt
        return schema.validate_json(
            json.dumps(
                {
                    "matches": [
                        {"sentence": 1, "excerpts": [1]},
                        {"sentence": 2, "excerpts": []},
                        {"sentence": 3, "excerpts": []},
                    ]
                }
            )
        )

    actual = await cite_missing_excerpts(raw, "[1] Battery log", {1, 2}, {}, identify)
    assert actual == raw.replace("lost power.", "lost power [1].")

    async def unexpected(*args):
        pytest.fail("A fully referenced draft needs no further request")

    complete = "The probes lost power [1].\n\nThe log covers one shift [2]."
    assert await cite_missing_excerpts(complete, "", {1}, {}, unexpected) == complete


@pytest.mark.parametrize(
    "rows",
    [[], [{"sentence": 1, "excerpts": [99]}], [{"sentence": 1, "excerpts": []}] * 2],
)
async def test_rejects_invalid_reference_assignments(rows):
    async def identify(system, prompt, history, config, schema):
        return schema.validate_python({"matches": rows})

    with pytest.raises(InvalidAssistantResponse):
        await cite_missing_excerpts(
            "The circuit opened.", "[1] Sensor log", {1}, {}, identify
        )


async def test_incorrect_sentence_number_gets_corrected_before_applying_citations():
    prompts = []

    async def identify(system, prompt, history, config, schema):
        prompts.append(prompt)
        number = 8 if len(prompts) == 1 else 1
        return schema.validate_python(
            {"matches": [{"sentence": number, "excerpts": [8]}]}
        )

    draft = await cite_missing_excerpts(
        "Pressure fell.", "[8] Pressure fell.", {8}, {}, identify
    )
    assert draft == "Pressure fell [8]."
    assert "invalid sentence numbers" in prompts[1] and "IDs: [1]" in prompts[1]


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("[3–5]", "[3, 4, 5]"),
        ("[3 - 5, 4, 1]", "[3, 4, 5, 1]"),
        ("[1, 5—5]", "[1, 5]"),
        ("[1, 3]", "[1, 3]"),
        ("[1–3]", "[1–3]"),
        ("[3-7]", "[3-7]"),
        ("[5-3]", "[5-3]"),
        ("[3-5, 99]", "[3-5, 99]"),
        ("[3-5,]", "[3-5,]"),
        ("[2018–2020]", "[2018–2020]"),
    ],
)
async def test_expand_excerpt_ranges_uses_only_supplied_labels(marker, expected):
    from ui.backend.services.brief_excerpt_citations import expand_excerpt_ranges

    assert expand_excerpt_ranges(f"An observation {marker}.", {1, 3, 4, 5}) == (
        f"An observation {expected}."
    )


async def test_range_citations_keep_the_finding_and_its_original_support():
    from unittest.mock import AsyncMock

    from ui.backend.services.assistant_brief_writer import (
        _brief_draft_text,
        _match_draft_citations,
    )

    request = AsyncMock()
    quotes = {3: (8, "low voltage"), 4: (8, "short duration"), 5: (10, "backup supply")}
    evidence = {
        8: {"text": "The log recorded low voltage and short duration."},
        10: {"text": "The backup supply started."},
    }
    text, retry = await _match_draft_citations(
        "The log recorded the drop [3–5].", "", quotes, {}, request, False, None
    )
    assert not retry
    request.assert_not_awaited()
    draft, issues, support = _brief_draft_text(text, evidence, set(), quotes)
    assert draft == "The log recorded the drop [8, 10]."
    assert issues == []
    assert [(src.citation, src.quote) for src in support[draft]] == list(
        quotes.values()
    )
