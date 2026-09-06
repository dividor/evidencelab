"""Integration tests for translation against the real translation service.

The unit tests in ``tests/unit/test_translation.py`` mock GoogleTranslator, so
they cannot catch real-service constraints — most importantly its hard
5000-character per-request cap, which silently broke AI-summary translation
(the bare except in ``translate_text`` returned the original English with a
200). These tests exercise the real service end-to-end, including an
AI-summary-sized text, so a regression in the chunked-translation path or a
service behaviour change is caught in CI rather than by users.

Requires outbound network access (runs in the integration job / Docker stack).
"""

import pytest

from ui.backend.services.llm_service import translate_text

pytestmark = pytest.mark.integration

_PARAGRAPH = (
    "The evaluation of the programme found significant improvements in school "
    "enrolment and retention, particularly for girls in rural districts [1]. "
    "Funding constraints nevertheless limited the scale-up of feeding "
    "programmes in the northern region [2].\n\n"
)


@pytest.mark.asyncio
async def test_search_chunk_sized_text_translates():
    """A typical search-result chunk translates to real French."""
    out = await translate_text(_PARAGRAPH.strip(), "fr", "en")

    assert out != _PARAGRAPH.strip()
    assert "évaluation" in out.lower() or "programme" in out.lower()
    assert "[1]" in out and "[2]" in out


@pytest.mark.asyncio
async def test_ai_summary_sized_text_translates_beyond_5000_chars():
    """An AI-summary-sized text (over the 5000-char cap) fully translates.

    This is the exact case that used to fail: GoogleTranslator rejects
    requests of 5000+ characters, and the failure was silently swallowed,
    returning the original English text.
    """
    long_text = "## Key findings\n\n" + _PARAGRAPH * 26
    assert len(long_text) > 5000  # sanity: must exercise the chunked path

    out = await translate_text(long_text, "fr", "en")

    # Actually translated — not the silently-returned original.
    assert out != long_text
    assert "évaluation" in out.lower() or "scolarisation" in out.lower()
    # Citations and paragraph structure survive chunking and restore.
    assert "[1]" in out and "[2]" in out
    assert out.count("\n\n") >= 20
    # No protection markers leak into the visible text.
    assert "__" not in out
