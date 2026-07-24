from unittest.mock import MagicMock, patch

import pytest

from ui.backend.services.llm_service import (
    _TRANSLATE_CHAR_LIMIT,
    _pack_units,
    translate_text,
)


@pytest.mark.asyncio
async def test_translate_text_basic():
    """Verify simple text translation works."""
    with patch(
        "ui.backend.services.llm_service.GoogleTranslator"
    ) as mock_translator_class:
        # Setup mock
        mock_instance = MagicMock()
        mock_instance.translate.return_value = "Bonjour le monde"
        mock_translator_class.return_value = mock_instance

        # Execute
        result = await translate_text("Hello world", "french")

        # Verify
        assert result == "Bonjour le monde"
        mock_translator_class.assert_called_with(source="auto", target="fr")
        mock_instance.translate.assert_called_with("Hello world")


@pytest.mark.asyncio
async def test_protection_logic():
    """Verify references and newlines are protected and restored."""
    with patch(
        "ui.backend.services.llm_service.GoogleTranslator"
    ) as mock_translator_class:
        # Setup mock to return the protected text "translated" (just echoing for verify)
        mock_instance = MagicMock()
        # Simulate what the translator might return (it verifies protected tokens are passed)
        # We will manually return a string that has the protected tokens "translated"
        # but in this case let's assume the translator preserves them.
        mock_instance.translate.return_value = (
            "Bonjour __REF_123__ le monde. __PARA__ C'est un test. __BR__ Merci."
        )
        mock_translator_class.return_value = mock_instance

        input_text = "Hello [123] world.\n\nThis is a test.\nThanks."

        # Execute
        result = await translate_text(input_text, "french")

        # Verify call arguments had protection
        # [123] -> __REF_123__
        # \n\n ->  __PARA__
        # \n ->  __BR__
        expected_call_arg = (
            "Hello __REF_123__ world. __PARA__ This is a test. __BR__ Thanks."
        )
        mock_instance.translate.assert_called_with(expected_call_arg)

        # Verify result has restored tokens
        expected_result = "Bonjour [123] le monde.\n\nC'est un test.\nMerci."
        assert result == expected_result


@pytest.mark.asyncio
async def test_translation_error_handling():
    """Verify exceptions are caught and original text is returned."""
    with patch(
        "ui.backend.services.llm_service.GoogleTranslator"
    ) as mock_translator_class:
        # Setup mock to raise exception
        mock_translator_class.side_effect = Exception("Translation service down")

        input_text = "Hello world"

        # Execute
        result = await translate_text(input_text, "french")

        # Verify original text returned
        assert result == input_text


@pytest.mark.asyncio
async def test_language_mapping():
    """Verify language codes are correctly mapped."""
    with patch(
        "ui.backend.services.llm_service.GoogleTranslator"
    ) as mock_translator_class:
        mock_instance = MagicMock()
        mock_instance.translate.return_value = "translated"
        mock_translator_class.return_value = mock_instance

        # Test "spanish" -> "es"
        await translate_text("text", "spanish")
        mock_translator_class.assert_called_with(source="auto", target="es")

        # Test "zh" -> "zh-CN"
        await translate_text("text", "zh")
        mock_translator_class.assert_called_with(source="auto", target="zh-CN")

        # Test unknown -> "en" default
        await translate_text("text", "klingon")
        mock_translator_class.assert_called_with(source="auto", target="en")


def test_pack_units_respects_limit_and_order():
    """Units are greedily packed under the limit, order preserved."""
    chunks = _pack_units(["aa", "bb", "cc", "dd"], limit=7, joiner="|")
    assert chunks == ["aa|bb", "cc|dd"]


def test_pack_units_oversized_unit_becomes_own_chunk():
    """A unit longer than the limit is emitted alone for further splitting."""
    chunks = _pack_units(["x" * 20, "yy"], limit=10, joiner=" ")
    assert chunks == ["x" * 20, "yy"]


@pytest.mark.asyncio
async def test_long_text_is_translated_in_chunks_under_the_cap():
    """AI-summary-sized text is split so every request stays under the cap.

    A single oversized request is rejected by GoogleTranslator with
    NotValidLength (>= 5000 chars), which previously made AI-summary
    translation silently return the original English text.
    """
    with patch(
        "ui.backend.services.llm_service.GoogleTranslator"
    ) as mock_translator_class:
        mock_instance = MagicMock()
        # Echo the input so restore logic and reassembly can be verified.
        mock_instance.translate.side_effect = lambda chunk: chunk
        mock_translator_class.return_value = mock_instance

        paragraph = (
            "The evaluation found significant improvements in enrolment "
            "and retention for girls in rural districts [1]. Funding "
            "constraints limited scale-up in the northern region [2]."
        )
        long_text = "## Key findings\n\n" + "\n\n".join([paragraph] * 40)
        assert len(long_text) > 5000  # sanity: the failing case

        result = await translate_text(long_text, "french", "en")

        # Multiple requests were made, and every one is under the hard cap.
        calls = [c.args[0] for c in mock_instance.translate.call_args_list]
        assert len(calls) > 1
        assert all(len(c) < 5000 for c in calls)
        # Round-trip through an identity translator preserves the content:
        # references and paragraph structure are restored intact.
        assert result == long_text


@pytest.mark.asyncio
async def test_short_text_still_translated_in_a_single_request():
    """Texts under the cap keep the original single-request behavior."""
    with patch(
        "ui.backend.services.llm_service.GoogleTranslator"
    ) as mock_translator_class:
        mock_instance = MagicMock()
        mock_instance.translate.side_effect = lambda chunk: chunk
        mock_translator_class.return_value = mock_instance

        text = "A short chunk-sized text [1].\n\nSecond paragraph."
        result = await translate_text(text, "french", "en")

        assert mock_instance.translate.call_count == 1
        assert result == text


@pytest.mark.asyncio
async def test_single_oversized_paragraph_is_split_on_sentences():
    """One paragraph above the cap is packed on sentence boundaries."""
    with patch(
        "ui.backend.services.llm_service.GoogleTranslator"
    ) as mock_translator_class:
        mock_instance = MagicMock()
        mock_instance.translate.side_effect = lambda chunk: chunk
        mock_translator_class.return_value = mock_instance

        sentence = "This is a fairly long sentence about programme outcomes. "
        one_paragraph = (
            sentence * ((_TRANSLATE_CHAR_LIMIT // len(sentence)) + 5)
        ).strip()
        assert len(one_paragraph) > _TRANSLATE_CHAR_LIMIT

        result = await translate_text(one_paragraph, "french", "en")

        calls = [c.args[0] for c in mock_instance.translate.call_args_list]
        assert len(calls) > 1
        assert all(len(c) < 5000 for c in calls)
        assert result == one_paragraph
