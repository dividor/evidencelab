"""Document fields distinguish evidence when titles and passages are ambiguous."""

import json

import pytest

from ui.backend.services.assistant_graph import _format_search_result
from ui.backend.services.assistant_grounding import render_evidence
from ui.backend.services.brief_evidence_selection import select_brief_evidence
from ui.backend.services.brief_repetition import remove_repeated_brief_findings

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]


async def test_brief_selection_carries_configured_fields_through_to_the_writer():
    fields = {"src_probe_model": "Probe model", "src_temperature": "Test temperature"}
    evidence = {}
    for index, version in enumerate(["Alpha", "Beta"], start=1):
        result = _format_search_result(
            {
                "title": "Calibration log",
                "text": "The display drifted during calibration.",
                "src_probe_model": version,
                "src_temperature": 0,
                "internal_note": "private",
            },
            fields,
        )
        result["global_index"] = index
        evidence[index] = result

    async def review(system, prompt, history, config, schema):
        assert '"Probe model": "Alpha"' in prompt
        assert '"Probe model": "Beta"' in prompt
        assert '"Test temperature": 0' in prompt
        assert "private" not in prompt
        return schema.validate_python(
            {
                "section_subject": "Beta probe",
                "passages": [{"citation": 2, "subject_line": 0, "finding_lines": [1]}],
            }
        )

    selected, (notes, quotes), _ = await select_brief_evidence(
        "Summarise calibration of Beta probes", evidence, {}, review, None
    )
    assert list(selected) == [2]
    assert quotes == {1: (2, "The display drifted during calibration.")}
    assert '"Probe model": "Beta"' in notes
    assert '"Probe model": "Beta"' in render_evidence(list(selected.values()))


async def test_repetition_requires_evidence_for_every_clause_before_removing_a_finding():
    draft = "The sensor was calibrated [1]. It also drifted under load [1]."
    earlier = [("Setup", "The sensor was calibrated.")]

    async def review(system, request, history, config, schema):
        assert len(json.loads(request)["new_section"]) == 2
        return schema.validate_python(
            {
                "duplicates": [
                    {
                        "id": 1,
                        "pairs": [
                            {
                                "new_clause": "The sensor was calibrated",
                                "existing_clause": "The sensor was calibrated",
                            }
                        ],
                    },
                    {
                        "id": 2,
                        "pairs": [
                            {
                                "new_clause": "It also drifted under load",
                                "existing_clause": "",
                            }
                        ],
                    },
                ]
            }
        )

    kept = await remove_repeated_brief_findings(draft, {}, review, earlier)
    assert kept == "It also drifted under load [1]."
