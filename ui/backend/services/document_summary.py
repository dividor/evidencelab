"""Document summaries generated, edited and saved from the Documents screen.

Summaries made here use the same text-to-summary logic as the pipeline
(``pipeline.processors.summarization.summary_text``), with the mode, sections
and prompt chosen in the app. The text comes from the document's stored
chunks, so sections can be chosen: the pipeline summarises before section
types exist, the app summarises afterwards.

A summary saved from the app is marked ``sys_summary_user_set``; the
pipeline keeps such a summary when the document is reprocessed, unless the
reprocess asks to replace it.
"""

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage

from pipeline.db.config import get_summarize_config
from pipeline.processors.summarization.summary_text import (
    MAX_MAP_WINDOWS,
    MODE_MAP_REDUCE,
    MODE_SINGLE_PROMPT,
    SUMMARY_USER_SET_FIELD,
    USE_CENTROID,
    ProgressCallback,
    SummaryTextMixin,
    SummaryTooLargeError,
    default_summary_instructions,
    resolve_summary_mode,
    single_prompt_limit_chars,
)
from pipeline.processors.tagging.tagger_constants import SECTION_TYPES
from pipeline.utilities.llm_retry import invoke_with_retry
from utils.llm_factory import get_llm

UPDATED_BY_FIELD = "sys_summary_updated_by"
UPDATED_AT_FIELD = "sys_summary_updated_at"

# sys_summarization_method values for summaries written in the app.
METHOD_BY_MODE = {
    MODE_MAP_REDUCE: "ui_map_reduce",
    MODE_SINGLE_PROMPT: "ui_single_prompt",
}
METHOD_EDITED = "ui_edited"

UNTAGGED = "untagged"
MAX_PROMPT_CHARS = 20000


class DocumentSummaryError(ValueError):
    """A problem with the request the user can act on; the message is shown."""


def summary_defaults(data_source: str) -> Dict[str, Any]:
    """Config defaults for app-generated summaries of a data source."""
    config = get_summarize_config(data_source)
    return {
        "mode": resolve_summary_mode(config),
        "section_types": configured_section_types(config),
        "prompt": default_summary_instructions(),
        "all_section_types": list(SECTION_TYPES),
        "single_prompt_context_window": config.get("single_prompt_context_window"),
    }


def configured_section_types(config: Dict[str, Any]) -> List[str]:
    """``summarize.section_types``; every section type when not set."""
    section_types = config.get("section_types", list(SECTION_TYPES))
    unknown = [s for s in section_types if s not in SECTION_TYPES]
    if unknown:
        raise ValueError(f"summarize.section_types has unknown types: {unknown}")
    return list(section_types)


def reading_order(
    doc_id: str, chunks: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """The chunks in document order.

    Chunk ids are ``uuid5(NAMESPACE_DNS, f"{doc_id}_{index}")`` (see
    ``IndexProcessor``), so the index is recovered from the id. A chunk whose id
    does not match is an error rather than a guess at its position.
    """
    position = {
        str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_{i}")): i
        for i in range(len(chunks))
    }
    unplaced = [c["id"] for c in chunks if c["id"] not in position]
    if unplaced:
        raise ValueError(
            f"Cannot order {len(unplaced)} chunk(s) of document {doc_id}: "
            "their ids do not follow the indexer's numbering"
        )
    return sorted(chunks, key=lambda c: position[c["id"]])


def section_breakdown(chunks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Characters of text per section type, in the standard section order."""
    totals: Dict[str, Dict[str, int]] = {}
    for chunk in chunks:
        key = chunk.get("tag_section_type") or UNTAGGED
        entry = totals.setdefault(key, {"chars": 0, "chunks": 0})
        entry["chars"] += len(chunk.get("sys_text") or "")
        entry["chunks"] += 1
    order = list(SECTION_TYPES) + [UNTAGGED]
    return [
        {"section_type": key, **totals[key]}
        for key in sorted(
            totals, key=lambda k: order.index(k) if k in order else len(order)
        )
    ]


def single_prompt_limit(data_source: str, max_tokens: int) -> Optional[int]:
    """Characters a single prompt can take with the default prompt; None when
    the data source has no single-prompt window configured."""
    window = get_summarize_config(data_source).get("single_prompt_context_window")
    if not window:
        return None
    return single_prompt_limit_chars(window, max_tokens, default_summary_instructions())


def has_section_types(chunks: Sequence[Dict[str, Any]]) -> bool:
    return any(chunk.get("tag_section_type") for chunk in chunks)


def select_text(
    doc_id: str, chunks: Sequence[Dict[str, Any]], section_types: Sequence[str]
) -> str:
    """The document's text, in order, from the chosen section types.

    A document without section types (not yet tagged) uses all its text; the
    caller tells the user so.
    """
    if not chunks:
        raise DocumentSummaryError("This document has no stored text to summarise")
    ordered = reading_order(doc_id, chunks)
    if has_section_types(ordered):
        wanted = set(section_types)
        ordered = [c for c in ordered if c.get("tag_section_type") in wanted]
    text = "\n\n".join((c.get("sys_text") or "").strip() for c in ordered).strip()
    if not text:
        raise DocumentSummaryError(
            "None of the chosen sections has any text in this document"
        )
    return text


class AppDocumentSummarizer(SummaryTextMixin):
    """Summarises text with the app's selected model and settings."""

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        mode: str,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: Optional[float],
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        self.config = config
        self.context_window = config.get("context_window", 29000)
        self.single_prompt_context_window = config.get("single_prompt_context_window")
        self.workers = config.get("llm_workers", 1)
        self.max_tokens = max_tokens
        self.model_key = model
        self.model_name = model
        self.summary_mode = mode
        self.summary_instructions = prompt
        self._progress = progress
        self.usage = UsageMetadataCallbackHandler()
        self._llm = get_llm(
            model=model, temperature=temperature, max_tokens=max_tokens
        ).with_config(callbacks=[self.usage])
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def calls(self) -> int:
        return self._calls

    def _invoke_llm(self, prompt: str, model: str, include_inference: bool) -> str:
        response = invoke_with_retry(self._llm, [HumanMessage(content=prompt)])
        with self._lock:
            self._calls += 1
        content = getattr(response, "content", response)
        return str(content).strip()

    def summarize(self, text: str) -> str:
        summary, _ = self._llm_summary(text)
        if summary == USE_CENTROID:
            raise SummaryTooLargeError(
                f"This text needs more than {MAX_MAP_WINDOWS} map-reduce parts; "
                "choose fewer sections."
            )
        if not summary:
            raise DocumentSummaryError("The model returned no summary")
        return summary


def generate_summary(
    data_source: str,
    doc_id: str,
    chunks: Sequence[Dict[str, Any]],
    *,
    mode: str,
    section_types: Sequence[str],
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: Optional[float],
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Generate (not save) a summary. Blocking: call it from a worker thread."""
    config = get_summarize_config(data_source)
    if mode not in METHOD_BY_MODE:
        raise DocumentSummaryError(f"Unknown summary mode: {mode}")
    if mode == MODE_SINGLE_PROMPT and not config.get("single_prompt_context_window"):
        raise DocumentSummaryError(
            "Single prompt is not available for this data source: "
            "summarize.single_prompt_context_window is not set"
        )
    text = select_text(doc_id, chunks, section_types)
    summarizer = AppDocumentSummarizer(
        config,
        mode=mode,
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        progress=progress,
    )
    summary = summarizer.summarize(text)
    return {
        "summary": summary,
        "mode": mode,
        "method": METHOD_BY_MODE[mode],
        "input_chars": len(text),
        "calls": summarizer.calls,
        "usage": summarizer.usage,
    }


def summary_updates(summary: str, method: str, user_email: str) -> Dict[str, Any]:
    """Document fields written when a summary is saved from the app."""
    return {
        "sys_full_summary": summary,
        "sys_summarization_method": method,
        SUMMARY_USER_SET_FIELD: True,
        UPDATED_BY_FIELD: user_email,
        UPDATED_AT_FIELD: datetime.now(timezone.utc).isoformat(),
    }
