"""Provider-neutral translation wrapper: language mapping, reference and
newline protection, chunking under the provider's request cap, and error
handling. Every test drives the real ``translate_text`` with a fake provider
so the behaviour is independent of Google Translate or any other backend."""

from typing import List, Tuple

import pytest

from ui.backend.services.translation_providers import (
    DEFAULT_REQUEST_CHAR_LIMIT,
    TranslationConfigError,
    TranslationDisabledError,
    TranslationProvider,
)
from ui.backend.services.translation_service import (
    _pack_units,
    resolve_language_code,
    translate_text,
)


class RecordingProvider(TranslationProvider):
    """Records every request and answers with a fixed reply or an echo."""

    name = "fake"

    def __init__(self, reply=None, limit: int = DEFAULT_REQUEST_CHAR_LIMIT):
        self.calls: List[Tuple[str, str, str]] = []
        self._reply = reply
        self.max_request_chars = limit

    def translate(self, text: str, source: str, target: str) -> str:
        self.calls.append((text, source, target))
        return self._reply if self._reply is not None else text


class FailingProvider(TranslationProvider):
    name = "failing"

    def translate(self, text: str, source: str, target: str) -> str:
        raise RuntimeError("Translation service down")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_translate_text_basic_passes_codes_to_provider():
    provider = RecordingProvider(reply="Bonjour le monde")

    result = await translate_text("Hello world", "french", provider=provider)

    assert result == "Bonjour le monde"
    assert provider.calls == [("Hello world", "auto", "fr")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_translate_text_protects_references_and_newlines():
    provider = RecordingProvider(
        reply="Bonjour __REF_123__ le monde. __PARA__ C'est un test. __BR__ Merci."
    )

    result = await translate_text(
        "Hello [123] world.\n\nThis is a test.\nThanks.", "french", provider=provider
    )

    assert provider.calls[0][0] == (
        "Hello __REF_123__ world. __PARA__ This is a test. __BR__ Thanks."
    )
    assert result == "Bonjour [123] le monde.\n\nC'est un test.\nMerci."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_translate_text_returns_original_when_provider_fails():
    result = await translate_text("Hello world", "french", provider=FailingProvider())

    assert result == "Hello world"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_translate_text_empty_input_is_empty_without_a_call():
    provider = RecordingProvider()

    assert await translate_text("", "french", provider=provider) == ""
    assert provider.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_translate_text_maps_names_codes_and_unknowns():
    provider = RecordingProvider()

    await translate_text("text", "spanish", provider=provider)
    await translate_text("text", "zh", provider=provider)
    await translate_text("text", "klingon", provider=provider)
    await translate_text("text", "German", "French", provider=provider)

    targets = [(c[1], c[2]) for c in provider.calls]
    assert targets == [("auto", "es"), ("auto", "zh"), ("auto", "en"), ("fr", "de")]


@pytest.mark.unit
def test_resolve_language_code_defaults():
    assert resolve_language_code(None, "auto") == "auto"
    assert resolve_language_code("Portuguese", "en") == "pt"
    assert resolve_language_code("xx", "en") == "en"


@pytest.mark.unit
def test_pack_units_respects_limit_and_order():
    assert _pack_units(["aa", "bb", "cc", "dd"], limit=7, joiner="|") == [
        "aa|bb",
        "cc|dd",
    ]


@pytest.mark.unit
def test_pack_units_oversized_unit_becomes_own_chunk():
    assert _pack_units(["x" * 20, "yy"], limit=10, joiner=" ") == ["x" * 20, "yy"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_text_is_translated_in_chunks_under_the_cap():
    """AI-summary-sized text is split so every request stays under the cap,
    and an identity round-trip preserves references and paragraphs."""
    provider = RecordingProvider()
    paragraph = (
        "The evaluation found significant improvements in enrolment "
        "and retention for girls in rural districts [1]. Funding "
        "constraints limited scale-up in the northern region [2]."
    )
    long_text = "## Key findings\n\n" + "\n\n".join([paragraph] * 40)
    assert len(long_text) > 5000

    result = await translate_text(long_text, "french", "en", provider=provider)

    assert len(provider.calls) > 1
    assert all(len(c[0]) <= DEFAULT_REQUEST_CHAR_LIMIT for c in provider.calls)
    assert result == long_text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_short_text_still_translated_in_a_single_request():
    provider = RecordingProvider()
    text = "A short chunk-sized text [1].\n\nSecond paragraph."

    result = await translate_text(text, "french", "en", provider=provider)

    assert len(provider.calls) == 1
    assert result == text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_single_oversized_paragraph_is_split_on_sentences():
    provider = RecordingProvider()
    sentence = "This is a fairly long sentence about programme outcomes. "
    one_paragraph = (
        sentence * ((DEFAULT_REQUEST_CHAR_LIMIT // len(sentence)) + 5)
    ).strip()
    assert len(one_paragraph) > DEFAULT_REQUEST_CHAR_LIMIT

    result = await translate_text(one_paragraph, "french", "en", provider=provider)

    assert len(provider.calls) > 1
    assert all(len(c[0]) <= DEFAULT_REQUEST_CHAR_LIMIT for c in provider.calls)
    assert result == one_paragraph


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chunking_honours_a_provider_specific_cap():
    """The wrapper reads the cap from the provider, not from a constant."""
    provider = RecordingProvider(limit=60)
    text = "\n\n".join(["Sentence number %d of the summary." % i for i in range(12)])

    result = await translate_text(text, "french", "en", provider=provider)

    assert len(provider.calls) > 1
    assert all(len(c[0]) <= 60 for c in provider.calls)
    assert result == text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_provider_propagates(monkeypatch):
    """``TRANSLATION_PROVIDER=off`` is a deployment decision, not a flaky
    endpoint, so it must not be swallowed into 'return the original text'."""
    from ui.backend.services import translation_providers

    monkeypatch.setenv("TRANSLATION_PROVIDER", "off")
    translation_providers.reset_translation_provider()

    with pytest.raises(TranslationDisabledError):
        await translate_text("Hello", "french")
    translation_providers.reset_translation_provider()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_misconfigured_provider_propagates(monkeypatch):
    from ui.backend.services import translation_providers

    monkeypatch.setenv("TRANSLATION_PROVIDER", "libretranslate")
    monkeypatch.delenv("LIBRETRANSLATE_URL", raising=False)
    translation_providers.reset_translation_provider()

    with pytest.raises(TranslationConfigError):
        await translate_text("Hello", "french")
    translation_providers.reset_translation_provider()
