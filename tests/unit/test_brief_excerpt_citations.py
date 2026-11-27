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
                [{"sentence": 1, "excerpts": [1]}, {"sentence": 2, "excerpts": []}]
            )
        )

    actual = await cite_missing_excerpts(raw, "[1] Battery log", {1, 2}, {}, identify)
    assert actual == raw.replace("lost power.", "lost power [1].")

    async def unexpected(*args):
        pytest.fail("A fully referenced draft needs no further request")

    complete = "The probes lost power [1].\n\nLimit: The duration is unclear."
    assert await cite_missing_excerpts(complete, "", {1}, {}, unexpected) == complete


@pytest.mark.parametrize(
    "rows",
    [[], [{"sentence": 1, "excerpts": [99]}], [{"sentence": 1, "excerpts": []}] * 2],
)
async def test_rejects_invalid_reference_assignments(rows):
    async def identify(system, prompt, history, config, schema):
        return schema.validate_python(rows)

    with pytest.raises(InvalidAssistantResponse):
        await cite_missing_excerpts(
            "The circuit opened.", "[1] Sensor log", {1}, {}, identify
        )
