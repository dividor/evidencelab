"""
summary_text.py - Text-to-summary logic shared by the pipeline and the UI.

Two modes, set by ``datasources.<name>.pipeline.summarize.mode``:

- ``map_reduce`` (default): text that fits the context window is summarised
  in one call; larger text is split into windows, each summarised, and the
  window summaries combined (recursing when they are still too large).
- ``single_prompt``: all the text goes to the LLM in one call. Text larger
  than ``single_prompt_context_window`` is an error naming both sizes.

The summary prompt (what the summary must contain) is
``prompts/summary_instructions.j2`` by default and can be replaced per call.
It follows the text block of ``summary_reduction.j2`` (map and single-prompt
steps) or ``summary_final.j2`` (combining step). It is appended after
rendering, not passed through the template, so the prompt's text is sent as
written while the document text keeps the templates' escaping.
"""

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader

from pipeline.utilities.logging_utils import _log_context

logger = logging.getLogger(__name__)

MODE_MAP_REDUCE = "map_reduce"
MODE_SINGLE_PROMPT = "single_prompt"
SUMMARY_MODES = (MODE_MAP_REDUCE, MODE_SINGLE_PROMPT)

# Marks a summary written or edited in the app; reprocessing keeps it unless
# the reprocess request clears the mark (see ui/backend/routes/documents.py).
SUMMARY_USER_SET_FIELD = "sys_summary_user_set"

# Returned by the map step when a document needs more windows than this; the
# pipeline then summarises a centroid extract instead.
MAX_MAP_WINDOWS = 200
USE_CENTROID = "USE_CENTROID"

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)
_reduction_template = _jinja_env.get_template("summary_reduction.j2")
_final_template = _jinja_env.get_template("summary_final.j2")

ProgressCallback = Callable[[Dict[str, Any]], None]


class SummaryTooLargeError(ValueError):
    """The text cannot be summarised within the configured limits."""


def default_summary_instructions() -> str:
    """The default summary prompt (``prompts/summary_instructions.j2``)."""
    return _jinja_env.get_template("summary_instructions.j2").render()


def resolve_summary_mode(config: Dict[str, Any]) -> str:
    """The configured summary mode; ``map_reduce`` when not set."""
    mode = config.get("mode", MODE_MAP_REDUCE)
    if mode not in SUMMARY_MODES:
        raise ValueError(
            f"summarize.mode must be one of {', '.join(SUMMARY_MODES)}, got {mode!r}"
        )
    return mode


def _with_instructions(rendered: str, instructions: str) -> str:
    return f"{rendered}\n\n{instructions}"


def render_map_prompt(document_text: str, instructions: str) -> str:
    """Prompt that summarises one piece of text (or all of it in one call)."""
    rendered = _reduction_template.render(document_text=document_text)
    return _with_instructions(rendered, instructions)


def render_reduce_prompt(map_summaries: str, instructions: str) -> str:
    """Prompt that combines the summaries of the pieces into one."""
    rendered = _final_template.render(map_summaries=map_summaries)
    return _with_instructions(rendered, instructions)


def clean_markdown(text: str) -> str:
    """Clean markdown formatting issues in LLM-generated text."""
    if not text:
        return text
    return re.sub(
        r"^(#{1,6})\s*\*\*\s*(.+?)\s*\*\*\s*$", r"\1 \2", text, flags=re.MULTILINE
    )


def token_budget_chars(context_window: int, max_tokens: int) -> int:
    """Convert a token-based context window to a character budget.

    Uses a conservative 1:1 chars-per-token ratio so that the rendered
    prompt stays within the model's token limit even for CJK, Khmer,
    and other scripts where each character may consume a full token.
    For Latin text this is overly cautious (typically ~4 chars/token)
    but the map-reduce strategy handles oversized documents correctly,
    so the only cost is a few extra LLM calls for large English docs.

    Args:
        context_window: Model context window in **tokens**.
        max_tokens: Tokens reserved for the LLM response.

    Returns:
        Maximum characters allowed for the document text portion.
    """
    _CHARS_PER_TOKEN = 1  # worst-case for CJK/Khmer/Thai scripts
    available_tokens = context_window - max_tokens
    return int(available_tokens * _CHARS_PER_TOKEN)


def effective_max_chars(max_chars: int, instructions: str) -> int:
    """Characters of text that fit once the prompt around it is counted."""
    overhead = len(render_map_prompt("", instructions)) + 100
    return max_chars - overhead


def single_prompt_limit_chars(
    single_prompt_context_window: Optional[int], max_tokens: int, instructions: str
) -> int:
    """Most characters of text a single prompt may carry."""
    if not single_prompt_context_window:
        raise ValueError(
            "summarize.single_prompt_context_window is not set; it is "
            "required for the single_prompt summary mode"
        )
    return effective_max_chars(
        token_budget_chars(single_prompt_context_window, max_tokens), instructions
    )


class SummaryTextMixin:
    """Summarise cleaned text in the configured mode.

    The host class provides ``context_window``, ``max_tokens``, ``workers``,
    ``config`` (for ``chunk_overlap``), ``model_key``, ``model_name`` and
    ``_invoke_llm(prompt, model, include_inference)``, and sets
    ``summary_mode``, ``summary_instructions`` and
    ``single_prompt_context_window``. ``_progress`` receives
    ``{"stage": "single" | "map" | "reduce", ...}`` events when set.
    """

    context_window: int
    max_tokens: int
    workers: int
    config: Dict[str, Any]
    model_key: str
    model_name: str
    summary_mode: str = MODE_MAP_REDUCE
    summary_instructions: str = ""
    single_prompt_context_window: Optional[int] = None
    _progress: Optional[ProgressCallback] = None

    def _invoke_llm(self, prompt: str, model: str, include_inference: bool) -> str:
        raise NotImplementedError

    def _instructions(self) -> str:
        return self.summary_instructions or default_summary_instructions()

    def _report(self, event: Dict[str, Any]) -> None:
        if self._progress is not None:
            self._progress(event)

    def _llm_summary(self, content: str) -> Tuple[Optional[str], Optional[str]]:
        """Summarise ``content`` in the configured mode."""
        if not content:
            return None, None
        cleaned = self._clean_llm_input(content)
        if not cleaned:
            return None, None

        logger.info("  Input: %s characters (mode %s)", len(cleaned), self.summary_mode)

        if self.summary_mode == MODE_SINGLE_PROMPT:
            self._check_single_prompt_fits(cleaned)
        try:
            if self.summary_mode == MODE_SINGLE_PROMPT:
                return self._single_pass_summary(cleaned)
            max_chars = token_budget_chars(self.context_window, self.max_tokens)
            effective_max = self._effective_max_chars(max_chars)
            if len(cleaned) <= effective_max:
                return self._single_pass_summary(cleaned)
            return self._map_reduce_summary(cleaned, max_chars, effective_max)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("  ✗ LLM summarization failed: %s", e)
            raise RuntimeError(f"LLM API call failed: {e}") from e

    def _check_single_prompt_fits(self, cleaned: str) -> None:
        limit = single_prompt_limit_chars(
            self.single_prompt_context_window, self.max_tokens, self._instructions()
        )
        if len(cleaned) > limit:
            raise SummaryTooLargeError(
                f"The text is {len(cleaned):,} characters, more than the "
                f"{limit:,} a single prompt can take "
                f"(summarize.single_prompt_context_window = "
                f"{self.single_prompt_context_window:,} tokens). Choose fewer "
                f"sections or use map reduce."
            )

    def _clean_llm_input(self, content: str) -> str:
        cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", content)
        cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"------- Page \d+ -------", "", cleaned)
        cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned)
        cleaned = re.sub(r" +", " ", cleaned).strip()
        return cleaned

    def _effective_max_chars(self, max_chars: int) -> int:
        return effective_max_chars(max_chars, self._instructions())

    @staticmethod
    def _token_budget_chars(context_window: int, max_tokens: int) -> int:
        return token_budget_chars(context_window, max_tokens)

    def _single_pass_summary(self, cleaned: str) -> Tuple[str, Optional[str]]:
        logger.info("  Single-pass summarization")
        self._report({"stage": "single"})
        prompt = render_map_prompt(cleaned, self._instructions())
        _log_prompt("LLM Summary Request (Single-pass)", "PROMPT:", prompt)
        summary = self._invoke_llm(prompt, self.model_key, include_inference=True)
        summary = clean_markdown(summary)
        _log_response(summary)
        if not summary or len(summary) < 50:
            raise ValueError(f"Response too short: {len(summary)} chars")
        logger.info("  ✓ Summary: %s characters", len(summary))
        return summary, None

    def _map_reduce_summary(
        self,
        cleaned: str,
        max_chars: int,
        effective_max: int,
        recursion_depth: int = 0,
    ) -> Tuple[str, Optional[str]]:
        """
        Execute map-reduce summarization with recursion support.

        Args:
            cleaned: Text to summarize
            max_chars: Maximum characters allowed in context window
            effective_max: Effective max chars after prompt overhead
            recursion_depth: Current recursion depth (default 0)

        Returns:
            Tuple[str, Optional[str]]: (final_summary, intermediate_summaries)
        """
        logger.info("  Using map-reduce strategy (depth %s)", recursion_depth)

        MAX_RECURSION_DEPTH = 3
        if recursion_depth > MAX_RECURSION_DEPTH:
            logger.warning(
                "  Max recursion depth (%s) reached. Returning combined summaries.",
                MAX_RECURSION_DEPTH,
            )
            return cleaned, cleaned  # Fallback to returning what we have

        chunks = self._split_chunks(cleaned, effective_max)
        logger.info("  Split into %s chunks", len(chunks))

        if len(chunks) > MAX_MAP_WINDOWS:  # Safety limit for extremely large documents
            logger.warning("  Too many chunks (%s) - will use centroid", len(chunks))
            return USE_CENTROID, None

        current_doc_id = getattr(_log_context, "doc_id", "N/A")
        chunk_summaries = self._summarize_chunks(chunks, current_doc_id)

        combined = "\n\n".join(chunk_summaries)
        logger.info("  Combined: %s characters", len(combined))

        # If combined is still too large, RECURSE
        if len(combined) > max_chars:
            logger.info(
                "  Combined summaries (%s chars) > max window (%s). Recursing...",
                len(combined),
                max_chars,
            )
            return self._map_reduce_summary(
                combined, max_chars, effective_max, recursion_depth + 1
            )

        self._report({"stage": "reduce", "depth": recursion_depth})
        prompt = render_reduce_prompt(combined, self._instructions())
        _log_prompt(
            f"LLM Summary Request (Final Reduction, Depth {recursion_depth})",
            "FINAL REDUCTION PROMPT:",
            prompt,
        )
        final = self._invoke_llm(prompt, self.model_name, include_inference=False)
        final = clean_markdown(final)
        _log_response(final)
        logger.info("  ✓ Final summary: %s characters", len(final))
        return final, combined

    def _split_chunks(self, text: str, effective_max: int) -> List[str]:
        chunks = []
        start = 0
        overlap = self.config.get("chunk_overlap", 800)
        while start < len(text):
            end = min(start + effective_max, len(text))
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - overlap
        return chunks

    def _summarize_chunks(self, chunks: List[str], current_doc_id: str) -> List[str]:
        done = _Counter()
        if self.workers == 1:
            logger.info("  Processing chunks sequentially (workers=1)")
            return [
                self._summarize_counted(idx, chunk, len(chunks), current_doc_id, done)[
                    1
                ]
                for idx, chunk in enumerate(chunks, 1)
            ]

        logger.info(
            "  Processing %s chunks with %s parallel workers",
            len(chunks),
            self.workers,
        )
        chunk_results = {}
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(
                    self._summarize_counted,
                    i,
                    chunk,
                    len(chunks),
                    current_doc_id,
                    done,
                ): i
                for i, chunk in enumerate(chunks, 1)
            }
            for future in as_completed(futures):
                idx, summary = future.result()
                chunk_results[idx] = summary
        return [chunk_results[idx] for idx in sorted(chunk_results.keys())]

    def _summarize_counted(
        self, idx: int, chunk: str, total: int, doc_id: str, done: "_Counter"
    ) -> Tuple[int, str]:
        result = self._summarize_chunk(idx, chunk, total, doc_id)
        self._report({"stage": "map", "done": done.increment(), "total": total})
        return result

    def _summarize_chunk(
        self, idx: int, chunk: str, total: int, doc_id: str
    ) -> Tuple[int, str]:
        _log_context.doc_id = doc_id
        logger.info("    Summarizing Chunk %s/%s...", idx, total)
        prompt = render_map_prompt(chunk, self._instructions())
        if idx == 1:
            _log_prompt(
                f"LLM Summary Request (Map-Reduce, Chunk {idx}/{total})",
                "CHUNK REDUCTION PROMPT:",
                prompt,
            )
        summary = self._invoke_llm(prompt, self.model_name, include_inference=False)
        return idx, summary


class _Counter:
    """Thread-safe count of finished map calls, for progress events."""

    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def increment(self) -> int:
        with self._lock:
            self._value += 1
            return self._value


def _log_prompt(title: str, label: str, prompt: str) -> None:
    logger.info("=" * 80)
    logger.info(title)
    logger.info("=" * 80)
    logger.info(label)
    logger.info(prompt[:500] + "..." if len(prompt) > 500 else prompt)
    logger.info("=" * 80)


def _log_response(text: str) -> None:
    logger.info("LLM RESPONSE:")
    logger.info(text[:500] + "..." if len(text) > 500 else text)
    logger.info("=" * 80)
