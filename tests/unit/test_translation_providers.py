"""Translation provider selection and each provider's request shape."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ui.backend.services import translation_providers as tp
from ui.backend.services.translation_providers import (
    GoogleTranslateProvider,
    LibreTranslateProvider,
    LlmTranslationProvider,
    TranslationConfigError,
    TranslationDisabledError,
    TranslationError,
    build_translation_provider,
    get_translation_provider,
    reset_translation_provider,
)


@pytest.fixture(autouse=True)
def _fresh_provider_cache():
    reset_translation_provider()
    yield
    reset_translation_provider()


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_provider_defaults_to_google_when_unset():
    assert isinstance(build_translation_provider({}), GoogleTranslateProvider)


@pytest.mark.unit
def test_build_provider_is_case_and_whitespace_tolerant():
    provider = build_translation_provider({"TRANSLATION_PROVIDER": "  Google "})
    assert provider.name == "google"


@pytest.mark.unit
def test_build_provider_off_raises_disabled():
    with pytest.raises(TranslationDisabledError, match="TRANSLATION_PROVIDER=off"):
        build_translation_provider({"TRANSLATION_PROVIDER": "off"})


@pytest.mark.unit
def test_build_provider_unknown_name_raises_config_error():
    with pytest.raises(TranslationConfigError, match="Unknown TRANSLATION_PROVIDER"):
        build_translation_provider({"TRANSLATION_PROVIDER": "bing"})


@pytest.mark.unit
def test_build_provider_libretranslate_requires_url():
    with pytest.raises(TranslationConfigError, match="LIBRETRANSLATE_URL"):
        build_translation_provider({"TRANSLATION_PROVIDER": "libretranslate"})


@pytest.mark.unit
def test_build_provider_libretranslate_reads_url_and_key():
    provider = build_translation_provider(
        {
            "TRANSLATION_PROVIDER": "libretranslate",
            "LIBRETRANSLATE_URL": "http://libretranslate:5000/",
            "LIBRETRANSLATE_API_KEY": "k",
        }
    )
    assert isinstance(provider, LibreTranslateProvider)
    assert provider._base_url == "http://libretranslate:5000"
    assert provider._api_key == "k"


@pytest.mark.unit
def test_build_provider_llm_reads_model_key():
    provider = build_translation_provider(
        {"TRANSLATION_PROVIDER": "llm", "TRANSLATION_LLM_MODEL": "gpt-4.1-mini"}
    )
    assert isinstance(provider, LlmTranslationProvider)
    assert provider._model_key == "gpt-4.1-mini"


@pytest.mark.unit
def test_get_translation_provider_caches_until_reset(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "google")
    first = get_translation_provider()
    monkeypatch.setenv("TRANSLATION_PROVIDER", "llm")
    assert get_translation_provider() is first

    reset_translation_provider()
    assert isinstance(get_translation_provider(), LlmTranslationProvider)


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_google_provider_calls_deep_translator_with_google_codes():
    with patch("deep_translator.GoogleTranslator") as translator_cls:
        translator_cls.return_value.translate.return_value = "你好"

        result = GoogleTranslateProvider().translate("hello", "auto", "zh")

    assert result == "你好"
    translator_cls.assert_called_once_with(source="auto", target="zh-CN")
    translator_cls.return_value.translate.assert_called_once_with("hello")


@pytest.mark.unit
def test_google_provider_returns_input_when_service_returns_nothing():
    with patch("deep_translator.GoogleTranslator") as translator_cls:
        translator_cls.return_value.translate.return_value = None

        assert GoogleTranslateProvider().translate("hello", "en", "fr") == "hello"


# ---------------------------------------------------------------------------
# LibreTranslate
# ---------------------------------------------------------------------------


def _response(payload, status=200):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.side_effect = (
        None if status < 400 else RuntimeError(f"HTTP {status}")
    )
    return response


@pytest.mark.unit
def test_libretranslate_posts_expected_payload_without_key():
    provider = LibreTranslateProvider("http://lt:5000", timeout=7)
    with patch.object(
        tp.requests, "post", return_value=_response({"translatedText": "hola"})
    ) as post:
        assert provider.translate("hello", "en", "es") == "hola"

    post.assert_called_once_with(
        "http://lt:5000/translate",
        json={"q": "hello", "source": "en", "target": "es", "format": "text"},
        timeout=7,
    )


@pytest.mark.unit
def test_libretranslate_includes_api_key_when_configured():
    token = "server-token"
    provider = LibreTranslateProvider("http://lt:5000", token)
    with patch.object(
        tp.requests, "post", return_value=_response({"translatedText": "x"})
    ) as post:
        provider.translate("hello", "auto", "fr")

    sent = post.call_args.kwargs["json"]
    assert sent["api_key"] == token


@pytest.mark.unit
def test_libretranslate_raises_on_http_error():
    provider = LibreTranslateProvider("http://lt:5000")
    with patch.object(tp.requests, "post", return_value=_response({}, status=500)):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            provider.translate("hello", "en", "fr")


@pytest.mark.unit
def test_libretranslate_raises_when_reply_lacks_text():
    provider = LibreTranslateProvider("http://lt:5000")
    with patch.object(tp.requests, "post", return_value=_response({"error": "bad"})):
        with pytest.raises(TranslationError, match="translatedText"):
            provider.translate("hello", "en", "fr")


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_llm_provider_uses_configured_model_at_zero_temperature():
    llm = MagicMock()
    llm.invoke.return_value = SimpleNamespace(content="  Bonjour __REF_1__  ")
    with patch("utils.llm_factory.get_llm", return_value=llm) as get_llm:
        provider = LlmTranslationProvider("my-model")
        result = provider.translate("Hello __REF_1__", "en", "fr")

    assert result == "Bonjour __REF_1__"
    get_llm.assert_called_once_with(
        model="my-model", temperature=0.0, max_tokens=tp._LLM_TRANSLATION_MAX_TOKENS
    )
    system, human = llm.invoke.call_args.args[0]
    assert "into French" in system.content
    assert "from English" in system.content
    assert "__REF_12__" in system.content  # placeholder-preservation rule
    assert human.content == "Hello __REF_1__"


@pytest.mark.unit
def test_llm_provider_prompt_asks_for_detection_when_source_is_auto():
    llm = MagicMock()
    llm.invoke.return_value = SimpleNamespace(content="x")
    with patch("utils.llm_factory.get_llm", return_value=llm):
        LlmTranslationProvider().translate("Hello", "auto", "de")

    system = llm.invoke.call_args.args[0][0].content
    assert "from its original language" in system
    assert "into German" in system
    assert "auto" not in system


@pytest.mark.unit
def test_llm_provider_rejects_empty_output():
    llm = MagicMock()
    llm.invoke.return_value = SimpleNamespace(content="   ")
    with patch("utils.llm_factory.get_llm", return_value=llm):
        with pytest.raises(TranslationError, match="empty"):
            LlmTranslationProvider().translate("Hello", "en", "fr")
