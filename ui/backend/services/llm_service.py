"""
LLM Service for generating AI summaries using LangChain
"""

import html
import json
import logging
import os
import re
import sys
import uuid as uuid_mod
from pathlib import Path
from typing import Any, Dict, List, Optional

from deep_translator import GoogleTranslator
from jinja2 import Environment, FileSystemLoader
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage

# Add utils to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from utils.langsmith_util import setup_langsmith_tracing  # noqa: E402
from utils.llm_factory import get_llm  # noqa: E402

# Setup LangSmith tracing
setup_langsmith_tracing()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangSmith trace URL helpers
# ---------------------------------------------------------------------------


def is_langsmith_tracing_enabled() -> bool:
    """Check if LangSmith tracing is enabled."""
    return os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true" and bool(
        os.getenv("LANGCHAIN_API_KEY")
    )


def _resolve_langsmith_url_prefix() -> Optional[str]:
    """Resolve the LangSmith project URL prefix (cached after first call)."""
    cache_attr = "_cached_prefix"
    if hasattr(_resolve_langsmith_url_prefix, cache_attr):
        return getattr(_resolve_langsmith_url_prefix, cache_attr)

    result: Optional[str] = None
    try:
        from langsmith import Client

        client = Client()
        tenant_id = client._get_tenant_id()
        project_name = os.getenv("LANGCHAIN_PROJECT", "default")
        project = client.read_project(project_name=project_name)
        host = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
        app_host = host.replace("api.", "").rstrip("/")
        if "api" in app_host:
            app_host = "https://smith.langchain.com"
        result = f"{app_host}/o/{tenant_id}/projects/p/{project.id}"
    except Exception as exc:
        logger.debug("Could not resolve LangSmith URL prefix: %s", exc)

    setattr(_resolve_langsmith_url_prefix, cache_attr, result)
    return result


def summarize_usage_metadata(
    handler: UsageMetadataCallbackHandler,
    model_key: Optional[str],
) -> Dict[str, Any]:
    """Collapse a ``UsageMetadataCallbackHandler`` into activity-log fields.

    The handler accumulates per-model usage as a nested dict; we sum
    across whichever models the LLM reported (typically just one) so a
    single PATCH call carries the totals plus the configured ``model_key``
    (the user-facing key from ``supported_llms``).
    """
    payload: Dict[str, Any] = {}
    if model_key:
        payload["llm_model"] = model_key
    try:
        per_model = handler.usage_metadata or {}
    except Exception:  # pragma: no cover - handler API surface
        per_model = {}
    if not per_model:
        return payload
    prompt = sum(int(v.get("input_tokens", 0) or 0) for v in per_model.values())
    completion = sum(int(v.get("output_tokens", 0) or 0) for v in per_model.values())
    if prompt:
        payload["prompt_tokens"] = prompt
    if completion:
        payload["completion_tokens"] = completion
    return payload


def get_langsmith_trace_url(run_id: uuid_mod.UUID) -> Optional[str]:
    """Construct LangSmith trace URL for a given run ID.

    Returns None if LangSmith tracing is not configured or the URL
    prefix could not be resolved.
    """
    if not is_langsmith_tracing_enabled():
        return None
    try:
        prefix = _resolve_langsmith_url_prefix()
        if prefix:
            return f"{prefix}/r/{run_id}?poll=true"
    except Exception:
        pass
    return None


# Initialize Jinja2 environment for prompt templates
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)

# Load templates at module level
_system_template = jinja_env.get_template("ai_summary_system.j2")
_user_template = jinja_env.get_template("ai_summary_user.j2")
_brief_outline_system_template = jinja_env.get_template("brief_outline_system.j2")
_brief_outline_user_template = jinja_env.get_template("brief_outline_user.j2")
_brief_revise_system_template = jinja_env.get_template("brief_revise_system.j2")
_brief_revise_user_template = jinja_env.get_template("brief_revise_user.j2")


def render_prompt(
    query: str,
    results: List[Dict[str, Any]],
    max_results: int = 20,
    system_prompt_override: str | None = None,
) -> str:
    """
    Render the full prompt for debugging/transparency purposes.

    Args:
        query: The search query string
        results: List of search results
        max_results: Maximum number of results to include
        system_prompt_override: Optional custom system prompt (from group settings)

    Returns:
        The fully rendered prompt text with system and user messages
    """
    # Limit to top N results
    top_results = results[:max_results]

    # Render prompts from templates (use override if provided)
    system_prompt = system_prompt_override or _system_template.render()
    user_prompt = _user_template.render(query=query, results=top_results)

    # Combine into full prompt
    full_prompt = f"SYSTEM MESSAGE:\n{system_prompt}\n\nUSER MESSAGE:\n{user_prompt}"

    return full_prompt


async def stream_ai_summary(
    query: str,
    results: List[Dict[str, Any]],
    max_results: int = 20,
    model_key: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    system_prompt_override: str | None = None,
):
    """
    Stream an AI summary of search results token by token.

    Args:
        query: The search query string
        results: List of search results (dictionaries with title, organization, text, etc.)
        max_results: Maximum number of results to include in the prompt (default: 20)
        system_prompt_override: Optional custom system prompt (from group settings)

    Yields:
        Individual tokens as they are generated by the LLM.
        The *last* yielded item is a dict with metadata including
        ``langsmith_trace_url`` when LangSmith tracing is active.
    """
    try:
        # Limit to top N results
        top_results = results[:max_results]

        # Render prompts from templates (use override if provided)
        system_prompt = system_prompt_override or _system_template.render()
        user_prompt = _user_template.render(query=query, results=top_results)

        logger.info(
            f"Streaming AI summary for query: '{query}' using {len(top_results)} results"
        )

        # Log the prompts
        logger.info("=" * 80)
        logger.info("AI Summary Request (Streaming)")
        logger.info("=" * 80)
        logger.info("SYSTEM PROMPT:")
        logger.info(system_prompt)
        logger.info("-" * 80)
        logger.info("USER PROMPT:")
        logger.info(user_prompt)
        logger.info("=" * 80)

        # Get LLM instance
        llm = get_llm(model=model_key, temperature=temperature, max_tokens=max_tokens)

        # Use LangChain's astream for async streaming
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        # Generate a deterministic run_id for LangSmith tracing
        run_id: Optional[uuid_mod.UUID] = None
        usage_handler = UsageMetadataCallbackHandler()
        config: Dict[str, Any] = {"callbacks": [usage_handler]}
        if is_langsmith_tracing_enabled():
            run_id = uuid_mod.uuid4()
            config["run_id"] = run_id

        # Stream tokens from the LLM
        accumulated = ""
        async for chunk in llm.astream(
            messages, config=config  # type: ignore[arg-type]
        ):
            if chunk.content:
                token = str(chunk.content)
                accumulated += token
                yield token

        logger.info(f"✓ Streamed AI summary ({len(accumulated)} chars)")

        # Yield metadata dict as final item (picked up by the route layer)
        metadata: Dict[str, Any] = summarize_usage_metadata(usage_handler, model_key)
        if run_id:
            trace_url = get_langsmith_trace_url(run_id)
            if trace_url:
                metadata["langsmith_trace_url"] = trace_url
        if metadata:
            yield metadata

    except Exception as e:
        logger.error(f"Error streaming AI summary: {e}", exc_info=True)
        raise


async def generate_ai_summary(
    query: str,
    results: List[Dict[str, Any]],
    max_results: int = 20,
    model_key: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    system_prompt_override: str | None = None,
) -> str:
    """
    Generate an AI summary of search results using LangChain + HuggingFace Inference API.

    Args:
        query: The search query string
        results: List of search results (dictionaries with title, organization, text, etc.)
        max_results: Maximum number of results to include in the prompt (default: 20)
        system_prompt_override: Optional custom system prompt (from group settings)

    Returns:
        Generated summary text
    """
    summary, _ = await generate_ai_summary_with_usage(
        query=query,
        results=results,
        max_results=max_results,
        model_key=model_key,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt_override=system_prompt_override,
    )
    return summary


async def generate_ai_summary_with_usage(
    query: str,
    results: List[Dict[str, Any]],
    max_results: int = 20,
    model_key: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    system_prompt_override: str | None = None,
) -> tuple[str, Dict[str, Any]]:
    """Generate an AI summary and return ``(summary, usage_metadata)``.

    ``usage_metadata`` carries the same shape emitted by the streaming
    endpoint: ``llm_model``, ``prompt_tokens``, ``completion_tokens``
    when the provider reports usage.
    """
    try:
        # Limit to top N results
        top_results = results[:max_results]

        # Render prompts from templates (use override if provided)
        system_prompt = system_prompt_override or _system_template.render()
        user_prompt = _user_template.render(query=query, results=top_results)

        logger.info(
            f"Generating AI summary for query: '{query}' using {len(top_results)} results"
        )

        # Log the prompts
        logger.info("=" * 80)
        logger.info("AI Summary Request")
        logger.info("=" * 80)
        logger.info("SYSTEM PROMPT:")
        logger.info(system_prompt)
        logger.info("-" * 80)
        logger.info("USER PROMPT:")
        logger.info(user_prompt)
        logger.info("=" * 80)

        # Get LLM instance
        llm = get_llm(model=model_key, temperature=temperature, max_tokens=max_tokens)

        # Use LangChain's ainvoke for async invocation with chat format
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        usage_handler = UsageMetadataCallbackHandler()
        response = await llm.ainvoke(
            messages, config={"callbacks": [usage_handler]}  # type: ignore[arg-type]
        )

        # Return raw content, matching the streaming endpoint behaviour
        summary = str(response.content).strip()

        # Log the response
        logger.info("AI SUMMARY RESPONSE:")
        logger.info(summary)
        logger.info("=" * 80)

        logger.info(f"✓ Generated AI summary ({len(summary)} chars)")

        usage = summarize_usage_metadata(usage_handler, model_key)
        return summary, usage

    except Exception as e:
        logger.error(f"Error generating AI summary: {e}", exc_info=True)
        raise


_FENCE_OPEN_RE = re.compile(r"^```[a-zA-Z]*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```$")
_LIST_PREFIX_RE = re.compile(r"^[\s\-\*•\d\.\)]+")


def _strip_code_fences(text: str) -> str:
    """Drop Markdown code fences the model may have wrapped the JSON in."""
    if text.startswith("```"):
        text = _FENCE_OPEN_RE.sub("", text)
        text = _FENCE_CLOSE_RE.sub("", text).strip()
    return text


def _extract_json_object(text: str) -> Any:
    """Best-effort parse of the first ``{...}`` object in ``text``, else None."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None


def _clean_heading(value: Any) -> tuple[str, int]:
    """Normalise one heading entry (dict or str) to ``(title, level)``."""
    if isinstance(value, dict):
        raw_title = value.get("title") or ""
        level = 2 if value.get("level") == 2 else 1
    else:
        raw_title = str(value)
        level = 1
    return raw_title.strip()[:120], level


def _headings_from_obj(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the heading list from a parsed ``{"headings": [...]}`` object."""
    headings: List[Dict[str, Any]] = []
    for h in obj.get("headings") or []:
        clean, level = _clean_heading(h)
        if clean:
            headings.append({"title": clean, "level": level})
    return headings


def _headings_from_lines(text: str) -> List[Dict[str, Any]]:
    """Fallback: treat each non-empty (de-bulleted) line as a level-1 heading."""
    headings: List[Dict[str, Any]] = []
    for line in text.splitlines():
        clean = _LIST_PREFIX_RE.sub("", line).strip()
        if clean and len(clean) <= 120:
            headings.append({"title": clean, "level": 1})
    return headings


def parse_brief_outline(
    raw: str, fallback_title: str = "Evidence Brief"
) -> tuple[str, List[Dict[str, Any]]]:
    """Parse an LLM outline response into ``(title, headings)``.

    Tolerant of code fences and stray prose around the JSON object. Each
    heading is normalised to ``{"title": str, "level": 1 | 2}``. Falls back to
    parsing a numbered/bulleted list, then to a single-section outline, so the
    caller always receives at least one heading with a level-1 first item.
    """
    text = _strip_code_fences((raw or "").strip())
    obj = _extract_json_object(text)

    title = (fallback_title or "Evidence Brief").strip() or "Evidence Brief"
    headings: List[Dict[str, Any]] = []
    if isinstance(obj, dict):
        if isinstance(obj.get("title"), str) and obj["title"].strip():
            title = obj["title"].strip()
        headings = _headings_from_obj(obj)

    # No JSON object at all — line-parse the prose. (A parsed-but-empty object
    # uses the Overview fallback below instead of line-parsing.)
    if not headings and not isinstance(obj, dict):
        headings = _headings_from_lines(text)

    if not headings:
        headings = [{"title": "Overview", "level": 1}]
    headings[0]["level"] = 1  # first item is always a top-level section
    return title, headings[:24]


async def generate_brief_outline(
    question: str,
    model_key: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    sources: Optional[List[Dict[str, Any]]] = None,
    instructions: str | None = None,
    num_headings: int | None = None,
) -> tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Generate research-brief section headings for a topic.

    ``question`` is the brief topic. ``instructions`` is optional author
    guidance, ``num_headings`` the desired number of top-level sections, and
    ``sources`` an optional sample of the most relevant document-library
    material (``{title, organization, year, snippet}``) so the headings are
    grounded in the themes actually present in the library. Prompts live in
    ``prompts/brief_outline_*.j2``.

    Returns ``(title, headings, usage)``; ``title`` falls back to the topic
    when the model does not supply one (callers typically force the title to
    the topic). Each heading is ``{"title": str, "level": 1 | 2}``; ``usage``
    is the token-usage payload from ``summarize_usage_metadata``.
    """
    system_prompt = _brief_outline_system_template.render()
    user_prompt = _brief_outline_user_template.render(
        topic=question.strip(),
        instructions=(instructions or "").strip() or None,
        num_headings=num_headings or 6,
        sources=sources or [],
    )
    llm = get_llm(
        model=model_key,
        temperature=temperature if temperature is not None else 0.2,
        max_tokens=max_tokens or 700,
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    usage_handler = UsageMetadataCallbackHandler()
    response = await llm.ainvoke(
        messages, config={"callbacks": [usage_handler]}  # type: ignore[arg-type]
    )
    raw = str(response.content).strip()
    logger.info("Brief outline raw response (%d chars): %s", len(raw), raw[:500])
    title, headings = parse_brief_outline(raw, fallback_title=question.strip())
    return title, headings, summarize_usage_metadata(usage_handler, model_key)


def _strip_section_wrapper(text: str) -> str:
    """Drop an accidental ```markdown fence or matching triple-quote wrapper the
    model sometimes adds around the returned section."""
    t = text.strip()
    if t.startswith("```"):
        # Remove leading ```lang line and a trailing ``` if present.
        lines = t.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    if t.startswith('"""') and t.endswith('"""') and len(t) >= 6:
        t = t[3:-3].strip()
    return t


async def revise_brief_section(
    content: str,
    instruction: str,
    model_key: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    voice_instructions: str | None = None,
) -> tuple[str, Dict[str, Any]]:
    """Surgically revise one brief section's markdown per an instruction.

    A single LLM call — NOT deep research — so the existing wording and inline
    ``[n]`` citation markers are preserved and only the smallest necessary
    changes are made. Returns ``(revised_markdown, usage)`` where ``usage`` is
    the token-usage payload from ``summarize_usage_metadata``.
    Prompts live in ``prompts/brief_revise_*.j2``.
    """
    # The shared prompt Jinja env autoescapes (Bandit requires it), but these
    # templates emit a plain-text LLM prompt, not HTML — escaping would turn
    # quotes into entities (&#34;) that the model then echoes back into the
    # revised section verbatim. The user template disables autoescape in-place
    # ({% autoescape false %}), so pass the values as plain strings; unescape
    # entities already baked into stored content by renders predating this fix.
    system_prompt = _brief_revise_system_template.render()
    user_prompt = _brief_revise_user_template.render(
        instruction=html.unescape(instruction.strip()),
        content=html.unescape(content),
        voice_instructions=(
            html.unescape(voice_instructions.strip()) if voice_instructions else None
        ),
    )
    llm = get_llm(
        model=model_key,
        temperature=temperature if temperature is not None else 0.2,
        max_tokens=max_tokens or 3000,
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    usage_handler = UsageMetadataCallbackHandler()
    response = await llm.ainvoke(
        messages, config={"callbacks": [usage_handler]}  # type: ignore[arg-type]
    )
    # Some models HTML-escape quotes/ampersands in their output (e.g. &#34;),
    # which would render literally in the section. Decode entities back to plain
    # text so the stored markdown is clean.
    revised = html.unescape(_strip_section_wrapper(str(response.content)))
    return revised, summarize_usage_metadata(usage_handler, model_key)


# GoogleTranslator rejects requests of 5000+ characters outright, so long
# texts (AI summaries easily exceed this; search-result chunks never do) must
# be translated in pieces. The margin below 5000 absorbs marker inflation and
# keeps every request safely inside the cap.
_TRANSLATE_CHAR_LIMIT = 4500


def _pack_units(units: List[str], limit: int, joiner: str) -> List[str]:
    """Greedily pack string units into chunks of at most ``limit`` characters.

    A single unit longer than ``limit`` becomes its own (oversized) chunk for
    the caller to split further.

    Args:
        units: Ordered pieces of text to pack.
        limit: Maximum chunk length in characters.
        joiner: String placed between units within a chunk.

    Returns:
        List of packed chunks, in order.
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


def _translate_oversized_paragraph(translator: GoogleTranslator, chunk: str) -> str:
    """Translate a single paragraph that alone exceeds the request cap.

    Splits on sentence ends first; a pathological single sentence is packed on
    word boundaries as a last resort.

    Args:
        translator: Configured GoogleTranslator instance.
        chunk: Protected paragraph text longer than the request cap.

    Returns:
        The translated paragraph.
    """
    out: List[str] = []
    for sentence_chunk in _pack_units(
        re.split(r"(?<=[.!?])\s+", chunk), _TRANSLATE_CHAR_LIMIT, " "
    ):
        if len(sentence_chunk) > _TRANSLATE_CHAR_LIMIT:
            word_chunks = _pack_units(
                sentence_chunk.split(" "), _TRANSLATE_CHAR_LIMIT, " "
            )
            out.extend(translator.translate(w) or w for w in word_chunks)
        else:
            out.append(translator.translate(sentence_chunk) or sentence_chunk)
    return " ".join(out)


def _translate_protected(translator: GoogleTranslator, protected: str) -> str:
    """Translate protected text, keeping every request under the service cap.

    Short texts go through in one request (the common search-result case).
    Longer texts (AI summaries) are split at paragraph markers — natural
    translation units — and each piece is translated separately, then
    re-joined with the paragraph marker so the restore step behaves exactly
    as in the single-request case.

    Args:
        translator: Configured GoogleTranslator instance.
        protected: Text with references and newlines already marker-protected.

    Returns:
        The translated text, markers preserved.
    """
    if len(protected) <= _TRANSLATE_CHAR_LIMIT:
        return translator.translate(protected)
    para_chunks = _pack_units(
        protected.split(" __PARA__ "), _TRANSLATE_CHAR_LIMIT, " __PARA__ "
    )
    return " __PARA__ ".join(
        (
            _translate_oversized_paragraph(translator, chunk)
            if len(chunk) > _TRANSLATE_CHAR_LIMIT
            else translator.translate(chunk) or chunk
        )
        for chunk in para_chunks
    )


async def translate_text(
    text: str, target_language: str, source_language: str | None = None
) -> str:
    """
    Translate text using deep-translator (Google Translate) instead of LLM.
    Uses regex to protect reference numbers like [64] from being mangled.

    Args:
        source_language: ISO code of the original text language.
            When provided, passed to GoogleTranslator instead of "auto".
    """
    if not text:
        return ""

    # Map full language names or codes to deep-translator ISO codes.
    # Note: "zh" is not accepted by GoogleTranslator; use "zh-CN".
    lang_map = {
        "english": "en",
        "french": "fr",
        "spanish": "es",
        "arabic": "ar",
        "chinese": "zh-CN",
        "portuguese": "pt",
        "russian": "ru",
        "swahili": "sw",
        "hindi": "hi",
        "bengali": "bn",
        "german": "de",
        "greek": "el",
        "italian": "it",
        "lithuanian": "lt",
        "vietnamese": "vi",
        "dutch": "nl",
        "polish": "pl",
        "turkish": "tr",
        "japanese": "ja",
        "korean": "ko",
        "en": "en",
        "fr": "fr",
        "es": "es",
        "ar": "ar",
        "zh": "zh-CN",
        "pt": "pt",
        "ru": "ru",
        "sw": "sw",
        "hi": "hi",
        "bn": "bn",
        "de": "de",
        "el": "el",
        "it": "it",
        "lt": "lt",
        "vi": "vi",
        "nl": "nl",
        "pl": "pl",
        "tr": "tr",
        "ja": "ja",
        "ko": "ko",
    }

    target_lang_code = lang_map.get(target_language.lower(), "en")
    source_lang_code = (
        lang_map.get(source_language.lower(), "auto") if source_language else "auto"
    )

    try:
        # 1. Protect references: [64] -> __REF_64__
        protected_text = text
        ref_pattern = r"\[(\d+)\]"
        refs = re.findall(ref_pattern, text)
        for ref_num in set(refs):
            protected_text = protected_text.replace(
                f"[{ref_num}]", f"__REF_{ref_num}__"
            )

        # 2. Protect newlines to prevent flattening
        # Replace \n\n with __PARA__ and \n with __BR__
        protected_text = protected_text.replace("\n\n", " __PARA__ ")
        protected_text = protected_text.replace("\n", " __BR__ ")

        # 3. Perform translation
        # deep-translator is synchronous, suitable for direct call here.
        # Long texts (e.g. AI summaries) are split into chunks below the
        # service's per-request character cap — a single oversized request
        # is rejected outright with NotValidLength.
        translator = GoogleTranslator(source=source_lang_code, target=target_lang_code)
        translated_text = _translate_protected(translator, protected_text)

        # 4. Restore references: __REF_64__ -> [64]
        if translated_text:
            # Restore references
            restore_ref_pattern = r"__\s*REF\s*_\s*(\d+)\s*__"

            def replace_match(match):
                return f"[{match.group(1)}]"

            final_text = re.sub(restore_ref_pattern, replace_match, translated_text)

            # Restore newlines (handling potential extra spaces added by translator)
            # __PARA__ -> \n\n
            final_text = re.sub(r"\s*__\s*PARA\s*__\s*", "\n\n", final_text)
            # __BR__ -> \n
            final_text = re.sub(r"\s*__\s*BR\s*__\s*", "\n", final_text)

            return final_text.strip()

        return text

    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return text
