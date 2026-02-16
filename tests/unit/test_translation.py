from unittest.mock import MagicMock, patch

import pytest

from ui.backend.services.llm_service import translate_text


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
