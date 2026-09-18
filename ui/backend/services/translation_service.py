"""Provider-neutral translation of user-facing text.

``translate_text`` is the one entry point the API routes use. It maps the
requested language to an ISO code, protects citation references such as
``[12]`` and paragraph breaks from being mangled, splits long texts into
pieces that fit the provider's request cap, and reassembles the result. The
provider that translates each piece comes from
:mod:`ui.backend.services.translation_providers` and is chosen by the
``TRANSLATION_PROVIDER`` environment variable.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from starlette.concurrency import run_in_threadpool

from ui.backend.services.translation_providers import (
    TranslationProvider,
    get_translation_provider,
)
from ui.backend.utils.language_codes import LANGUAGE_NAMES

logger = logging.getLogger(__name__)

# Language names (lower-cased) or ISO 639-1 codes accepted from the UI, mapped
# to codes. Provider-specific spellings (Google's ``zh-CN``) are applied by
# the provider, not here.
_LANGUAGE_LOOKUP = {name.lower(): code for code, name in LANGUAGE_NAMES.items()}
_LANGUAGE_LOOKUP.update({code: code for code in LANGUAGE_NAMES})

_REF_PATTERN = r"\[(\d+)\]"
_RESTORE_REF_PATTERN = r"__\s*REF\s*_\s*(\d+)\s*__"
_PARA_MARKER = " __PARA__ "
_BR_MARKER = " __BR__ "


def resolve_language_code(language: Optional[str], default: str) -> str:
    """Map a UI language name or code to an ISO code, else ``default``."""
    if not language:
        return default
    return _LANGUAGE_LOOKUP.get(language.strip().lower(), default)


def _pack_units(units: List[str], limit: int, joiner: str) -> List[str]:
    """Greedily pack string units into chunks of at most ``limit`` characters.

    A single unit longer than ``limit`` becomes its own (oversized) chunk for
    the caller to split further.
    """
    chunks: List[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}{joiner}{unit}" if current else unit
        if not current or len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)
    return chunks


def _translate_oversized_paragraph(
    provider: TranslationProvider, source: str, target: str, chunk: str
) -> str:
    """Translate a single paragraph that alone exceeds the request cap.

    Splits on sentence ends first; a pathological single sentence is packed on
    word boundaries as a last resort.
    """
    limit = provider.max_request_chars
    out: List[str] = []
    for sentence_chunk in _pack_units(re.split(r"(?<=[.!?])\s+", chunk), limit, " "):
        if len(sentence_chunk) > limit:
            word_chunks = _pack_units(sentence_chunk.split(" "), limit, " ")
            out.extend(provider.translate(w, source, target) or w for w in word_chunks)
        else:
            out.append(
                provider.translate(sentence_chunk, source, target) or sentence_chunk
            )
    return " ".join(out)


def _translate_protected(
    provider: TranslationProvider, source: str, target: str, protected: str
) -> str:
    """Translate protected text, keeping every request under the provider cap.

    Short texts go through in one request (the common search-result case).
    Longer texts (AI summaries) are split at paragraph markers, translated
    piece by piece, and re-joined with the marker so the restore step behaves
    exactly as in the single-request case.
    """
    limit = provider.max_request_chars
    if len(protected) <= limit:
        return provider.translate(protected, source, target)
    para_chunks = _pack_units(protected.split(_PARA_MARKER), limit, _PARA_MARKER)
    return _PARA_MARKER.join(
        (
            _translate_oversized_paragraph(provider, source, target, chunk)
            if len(chunk) > limit
            else provider.translate(chunk, source, target) or chunk
        )
        for chunk in para_chunks
    )


def _protect(text: str) -> str:
    """Replace references and newlines with markers translators leave alone."""
    protected = text
    for ref_num in set(re.findall(_REF_PATTERN, text)):
        protected = protected.replace(f"[{ref_num}]", f"__REF_{ref_num}__")
    protected = protected.replace("\n\n", _PARA_MARKER)
    return protected.replace("\n", _BR_MARKER)


def _restore(translated: str) -> str:
    """Turn markers back into references and newlines."""
    restored = re.sub(_RESTORE_REF_PATTERN, lambda m: f"[{m.group(1)}]", translated)
    restored = re.sub(r"\s*__\s*PARA\s*__\s*", "\n\n", restored)
    restored = re.sub(r"\s*__\s*BR\s*__\s*", "\n", restored)
    return restored.strip()


async def translate_text(
    text: str,
    target_language: str,
    source_language: Optional[str] = None,
    provider: Optional[TranslationProvider] = None,
) -> str:
    """Translate ``text`` into ``target_language`` with the configured provider.

    Args:
        text: Text to translate. Citation references like ``[64]`` and line
            breaks are preserved.
        target_language: Language name or ISO code; unknown values mean English.
        source_language: ISO code of the original text; ``None`` lets the
            provider detect it.
        provider: Override the configured provider (tests).

    Raises:
        TranslationDisabledError: when ``TRANSLATION_PROVIDER=off``.
        TranslationConfigError: when the configured provider is unusable.

    A provider failure on an otherwise valid configuration is logged and the
    original text is returned, so a flaky third-party endpoint degrades a
    result to its source language rather than failing the whole request.
    """
    if not text:
        return ""
    active = provider or get_translation_provider()
    target = resolve_language_code(target_language, "en")
    source = resolve_language_code(source_language, "auto")
    try:
        protected = _protect(text)
        translated = await run_in_threadpool(
            _translate_protected, active, source, target, protected
        )
        return _restore(translated) if translated else text
    except Exception as exc:
        logger.error("Translation failed (%s): %s", active.name, exc)
        return text
