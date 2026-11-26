"""
Research Assistant service.

Streams research progress and sends conversation sources and model usage to callers.
"""

import logging
import math
import uuid as uuid_mod
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage

from ui.backend.services.assistant_graph import build_research_agent
from ui.backend.services.assistant_settings import AssistantSettings
from ui.backend.services.llm_service import summarize_usage_metadata
from utils.llm_factory import get_llm

logger = logging.getLogger(__name__)


# Token ceiling for a requested length in words. English prose runs at about
# 1.3 tokens per word; inline [n] citations and markdown headings push that
# up, and the model needs room to finish its last sentence rather than be cut
# off mid-citation, hence the ratio and the fixed headroom.
TOKENS_PER_WORD = 1.6
TARGET_LENGTH_HEADROOM_TOKENS = 400


def max_tokens_for_target(
    max_tokens: Optional[int], target_words: Optional[int]
) -> Optional[int]:
    """Raise the configured ``max_tokens`` so a ``target_words`` answer fits.

    The configured ceiling (e.g. 2000 tokens, roughly 1,400 words) silently
    truncates longer targets, so when a target is given the ceiling becomes
    at least what that many words need. It is never lowered: a small target
    is enforced by the prompt (and the Brief's condense pass), not by cutting
    the model off, which would also starve the researcher sub-agent that
    shares this limit.
    """
    if not target_words:
        return max_tokens
    needed = math.ceil(target_words * TOKENS_PER_WORD) + TARGET_LENGTH_HEADROOM_TOKENS
    return max(max_tokens or 0, needed)


def _get_llm(model_key=None, temperature=None, max_tokens=None):
    """Get LLM instance via the factory."""
    return get_llm(
        model=model_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _get_trace_url(run_id: uuid_mod.UUID) -> Optional[str]:
    """Trace link for ``run_id`` from the configured tracing backend, if any."""
    try:
        from ui.backend.services.llm_service import get_trace_url

        return get_trace_url(run_id)
    except Exception:
        return None


def _trace_callbacks() -> List[Any]:
    """LangChain callbacks the tracing backend needs on the agent's config."""
    from utils.tracing import get_trace_recorder

    return get_trace_recorder().callbacks()


def _build_conversation_messages(
    conversation_messages: Optional[List[Dict[str, Any]]] = None,
) -> List:
    """Build LangChain message objects from conversation history."""
    messages: List = []
    if conversation_messages:
        for msg in conversation_messages[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
    return messages


def _extract_prior_sources(
    conversation_messages: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Collect every cited source from prior assistant turns, deduped by index.

    Sources are stored per-message in the SSE/persistence shape and carry
    a stable ``index`` (the global citation number). Merging by index keeps
    one entry per citation across the whole thread so a follow-up turn can
    re-use those numbers without renumbering.
    """
    if not conversation_messages:
        return []
    by_idx: Dict[int, Dict[str, Any]] = {}
    for msg in conversation_messages:
        if msg.get("role") != "assistant":
            continue
        for src in msg.get("sources") or []:
            idx = src.get("index")
            if isinstance(idx, int):
                by_idx[idx] = src
    return [by_idx[k] for k in sorted(by_idx.keys())]


def _build_done_event(
    run_id: uuid_mod.UUID,
    usage_handler: Optional[UsageMetadataCallbackHandler] = None,
    model_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the completion event with an optional trace URL.

    ``trace_url`` is the vendor-neutral key; ``langsmith_trace_url`` is
    emitted alongside it for one release so older frontend bundles keep
    reading it.

    When *usage_handler* is provided, attach the accumulated token usage
    (summed across every LLM hop the agent took) and the configured
    ``model_key`` so the frontend can include them in the activity log
    POST.
    """
    done_event: Dict[str, Any] = {
        "type": "done",
        "messageId": str(uuid_mod.uuid4()),
        # The agent run behind this turn; a Brief stores it with the
        # section's original so a reviewer can match stored output to the
        # trace and the usage record.
        "runId": str(run_id),
    }
    trace_url = _get_trace_url(run_id)
    if trace_url:
        done_event["trace_url"] = trace_url
        done_event["langsmith_trace_url"] = trace_url
    if usage_handler is not None:
        usage = summarize_usage_metadata(usage_handler, model_key)
        if usage:
            done_event["usage"] = usage
    return done_event


async def stream_research_response(
    query: str,
    data_source: Optional[str] = None,
    model_key: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    conversation_messages: Optional[List[Dict[str, Any]]] = None,
    reranker_model: Optional[str] = None,
    search_settings: Optional[Dict[str, Any]] = None,
    system_prompt_override: Optional[str] = None,
    deep_research: bool = False,
    target_words: Optional[int] = None,
    introduces_sub_sections: Optional[List[str]] = None,
    assistant_settings: Optional[AssistantSettings] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream progress and the final cited answer for either research mode."""
    from ui.backend.utils.app_state import validate_data_source

    data_source = validate_data_source(data_source)
    run_id = uuid_mod.uuid4()
    usage = UsageMetadataCallbackHandler()
    try:
        llm = _get_llm(
            model_key, temperature, max_tokens_for_target(max_tokens, target_words)
        )
        graph, tracker, search_budget = build_research_agent(
            llm,
            data_source,
            reranker_model,
            search_settings,
            system_prompt_override,
            _extract_prior_sources(conversation_messages),
            deep_research=deep_research,
            target_words=target_words,
            introduces_sub_sections=introduces_sub_sections,
            assistant_settings=assistant_settings,
        )
        yield {"type": "phase", "phase": "planning"}
        async for event in graph.astream(
            {
                "query": query,
                "messages": _build_conversation_messages(conversation_messages),
            },
            config={
                "run_id": run_id,
                "recursion_limit": 2 * search_budget + 3,
                "callbacks": [usage, *_trace_callbacks()],
            },
            stream_mode="custom",
        ):
            yield event
        sources = tracker.get_sources()
        if sources:
            yield {"type": "sources", "sources": sources}
        yield _build_done_event(run_id, usage_handler=usage, model_key=model_key)
    except Exception:
        logger.exception("Assistant research failed (run_id=%s)", run_id)
        yield {
            "type": "error",
            "error": "The Assistant could not complete this request.",
        }
