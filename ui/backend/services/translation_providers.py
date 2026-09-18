"""Translation providers behind one project-owned interface.

Evidence Lab translates search results, AI summaries and document text on
request. The service that does the work is chosen by ``TRANSLATION_PROVIDER``:

- ``google`` (default): Google Translate through the MIT-licensed
  ``deep-translator`` library. Needs no key, but every request goes to a
  third-party service.
- ``libretranslate``: a LibreTranslate server (AGPL, self-hostable). Needs
  ``LIBRETRANSLATE_URL``; add ``LIBRETRANSLATE_API_KEY`` when the server
  requires one.
- ``llm``: the deployment's own configured LLM via ``utils.llm_factory``.
  ``TRANSLATION_LLM_MODEL`` picks a model key from ``config.json``; unset
  means the default model.
- ``off``: translation is disabled. The translate endpoints answer 501.

A provider translates one piece of text that already fits its request cap.
Reference protection, paragraph chunking and language-name mapping live in
``translation_service`` and are shared by every provider, so adding a new
provider means implementing :meth:`TranslationProvider.translate` only.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping, Optional

import requests
from jinja2 import Environment, FileSystemLoader

from ui.backend.utils.language_codes import LANGUAGE_NAMES

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "google"
PROVIDER_ENV = "TRANSLATION_PROVIDER"

# Google Translate rejects requests of 5000+ characters outright. The margin
# below 5000 absorbs marker inflation and keeps every request inside the cap.
# LibreTranslate and LLMs have no such hard limit, but the same size keeps
# requests short enough to be reliable, so it is the default for all.
DEFAULT_REQUEST_CHAR_LIMIT = 4500

# Output room for an LLM translating one chunk: chunks are at most
# ``DEFAULT_REQUEST_CHAR_LIMIT`` characters, and a translation can run longer
# than its source in token terms.
_LLM_TRANSLATION_MAX_TOKENS = 4096


class TranslationError(RuntimeError):
    """A provider could not translate the text."""


class TranslationDisabledError(TranslationError):
    """Translation is switched off on this deployment."""


class TranslationConfigError(TranslationError):
    """The selected provider is missing a required setting."""


class TranslationProvider(ABC):
    """One translation backend.

    ``translate`` receives text that is already at most ``max_request_chars``
    long, with reference markers such as ``__REF_12__`` and paragraph markers
    such as ``__PARA__`` embedded; providers must return them unchanged.
    ``source`` and ``target`` are ISO 639-1 codes (``source`` may be ``auto``).
    """

    name: str = ""
    max_request_chars: int = DEFAULT_REQUEST_CHAR_LIMIT

    @abstractmethod
    def translate(self, text: str, source: str, target: str) -> str:
        """Translate ``text`` from ``source`` into ``target``."""


class GoogleTranslateProvider(TranslationProvider):
    """Google Translate via ``deep-translator`` (the historical default)."""

    name = "google"

    # Google's web endpoint does not accept the bare ``zh`` code.
    _CODE_OVERRIDES = {"zh": "zh-CN"}

    def _code(self, code: str) -> str:
        return self._CODE_OVERRIDES.get(code, code)

    def translate(self, text: str, source: str, target: str) -> str:
        from deep_translator import GoogleTranslator

        translator = GoogleTranslator(
            source=self._code(source), target=self._code(target)
        )
        return translator.translate(text) or text


class LibreTranslateProvider(TranslationProvider):
    """A LibreTranslate server, self-hosted or public.

    Talks to the ``POST /translate`` endpoint directly rather than through
    ``deep-translator``, whose LibreTranslate client insists on an API key
    that a self-hosted server does not need.
    """

    name = "libretranslate"

    def __init__(
        self, base_url: str, api_key: Optional[str] = None, timeout: float = 60.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or None
        self._timeout = timeout

    def translate(self, text: str, source: str, target: str) -> str:
        payload = {"q": text, "source": source, "target": target, "format": "text"}
        if self._api_key:
            payload["api_key"] = self._api_key
        response = requests.post(
            f"{self._base_url}/translate", json=payload, timeout=self._timeout
        )
        response.raise_for_status()
        translated = response.json().get("translatedText")
        if not isinstance(translated, str):
            raise TranslationError("LibreTranslate response carried no translatedText")
        return translated


_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


class LlmTranslationProvider(TranslationProvider):
    """Translate with the deployment's configured LLM.

    Uses the same ``utils.llm_factory`` path as every other LLM call, so the
    model, provider and credentials are whatever ``config.json`` and the
    environment already define. Temperature is pinned to 0 for faithful
    output.
    """

    name = "llm"

    def __init__(self, model_key: Optional[str] = None) -> None:
        self._model_key = model_key or None
        env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)), autoescape=True)
        self._system_template = env.get_template("translate_system.j2")

    def translate(self, text: str, source: str, target: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        from utils.llm_factory import get_llm

        llm = get_llm(
            model=self._model_key,
            temperature=0.0,
            max_tokens=_LLM_TRANSLATION_MAX_TOKENS,
        )
        system_prompt = self._system_template.render(
            source=None if source == "auto" else LANGUAGE_NAMES.get(source, source),
            target=LANGUAGE_NAMES.get(target, target),
        )
        response = llm.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=text)]
        )
        translated = str(response.content).strip()
        if not translated:
            raise TranslationError("LLM returned an empty translation")
        return translated


def build_translation_provider(env: Mapping[str, str]) -> TranslationProvider:
    """Construct the provider named by ``TRANSLATION_PROVIDER`` in ``env``.

    Raises:
        TranslationDisabledError: when the provider is ``off``.
        TranslationConfigError: for an unknown name or a missing setting.
    """
    name = (env.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip().lower()
    if name == "off":
        raise TranslationDisabledError(
            f"Translation is disabled on this deployment ({PROVIDER_ENV}=off)"
        )
    if name == "google":
        return GoogleTranslateProvider()
    if name == "libretranslate":
        base_url = (env.get("LIBRETRANSLATE_URL") or "").strip()
        if not base_url:
            raise TranslationConfigError(
                f"{PROVIDER_ENV}=libretranslate requires LIBRETRANSLATE_URL"
            )
        return LibreTranslateProvider(base_url, env.get("LIBRETRANSLATE_API_KEY"))
    if name == "llm":
        return LlmTranslationProvider(env.get("TRANSLATION_LLM_MODEL"))
    raise TranslationConfigError(
        f"Unknown {PROVIDER_ENV} '{name}'; expected google, libretranslate, llm or off"
    )


_provider: Optional[TranslationProvider] = None


def get_translation_provider() -> TranslationProvider:
    """Return the process-wide provider, building it on first use."""
    global _provider
    if _provider is None:
        _provider = build_translation_provider(os.environ)
        logger.info("Translation provider: %s", _provider.name)
    return _provider


def reset_translation_provider() -> None:
    """Forget the cached provider so the next call re-reads the environment."""
    global _provider
    _provider = None
