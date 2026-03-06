import json
import logging
import os
import sys

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ui.backend.schemas import AISummaryRequest, AISummaryResponse, TranslateRequest
from ui.backend.services import llm_service as llm_service_module
from ui.backend.utils.app_limits import (
    get_rate_limit_translate,
    get_rate_limits,
    limiter,
)
from ui.backend.utils.app_state import logger

_RATE_LIMIT_SEARCH, _RATE_LIMIT_DEFAULT, RATE_LIMIT_AI = get_rate_limits()
RATE_LIMIT_TRANSLATE = get_rate_limit_translate()
router = APIRouter()

# ---------------------------------------------------------------------------
# Conditional user-module imports (same pattern as config.py)
# ---------------------------------------------------------------------------
_UM_RAW = os.environ.get("USER_MODULE", "off").lower()
_USER_MODULE = _UM_RAW not in ("off", "0", "false", "no")

if _USER_MODULE:
    from ui.backend.auth.db import get_async_session as _get_session_dep
    from ui.backend.auth.models import UserGroup, UserGroupMember
    from ui.backend.auth.users import optional_current_user as _resolve_user_dep
else:

    async def _noop_user():  # type: ignore[misc]
        return None

    async def _noop_session():  # type: ignore[misc]
        return None

    _resolve_user_dep = _noop_user  # type: ignore[assignment]
    _get_session_dep = _noop_session  # type: ignore[assignment]


def _get_llm_service():
    """Resolve the LLM service module from runtime or fallback imports."""
    return (
        sys.modules.get("llm_service")
        or sys.modules.get("ui.backend.services.llm_service")
        or llm_service_module
    )


async def _resolve_summary_prompt(user, session) -> str | None:
    """Return the first non-null summary_prompt from the user's groups."""
    if not _USER_MODULE or user is None or session is None:
        return None
    stmt = (
        select(UserGroup.summary_prompt, UserGroup.name, UserGroup.is_default)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .where(
            UserGroupMember.user_id == user.id,
            UserGroup.summary_prompt.isnot(None),
            UserGroup.summary_prompt != "",
        )
        .order_by(UserGroup.is_default, UserGroup.name)
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row:
        prompt, group_name, is_default = row
        user_email = getattr(user, "email", "unknown")
        logger.info(
            "Resolved summary prompt for user=%s from group=%s (default=%s), len=%d",
            user_email,
            group_name,
            is_default,
            len(prompt),
        )
        return prompt
    logger.info(
        "No group summary prompt found for user=%s", getattr(user, "email", "unknown")
    )
    return None


@router.post("/translate")
@limiter.limit(RATE_LIMIT_TRANSLATE)
async def translate(request: Request, body: TranslateRequest):
    """
    Translate text to the target language using the LLM.
    """
    try:
        logging.info(
            "Translation Request: len=%s, source=%s, target=%s, text_preview='%s'",
            len(body.text),
            body.source_language,
            body.target_language,
            body.text[:100],
        )
        llm_service = _get_llm_service()
        translated_text = await llm_service.translate_text(
            body.text, body.target_language, body.source_language
        )
        logging.info(
            "Translation Result: len=%s, text_preview='%s'",
            len(translated_text),
            translated_text[:100],
        )

        return {"translated_text": translated_text}

    except Exception as e:
        logger.error(f"Translation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-summary/stream")
@limiter.limit(RATE_LIMIT_AI)
async def stream_summary(
    request: Request,
    body: AISummaryRequest,
    user=Depends(_resolve_user_dep),
    session=Depends(_get_session_dep),
):
    """
    Stream an AI summary of search results using HuggingFace LLM via LangChain.
    Returns Server-Sent Events (SSE) for progressive display.
    """
    # Resolve group-level summary prompt override (if user is logged in)
    system_prompt_override = await _resolve_summary_prompt(user, session)

    async def event_generator():
        """Stream summary tokens and completion events as SSE."""
        try:
            llm_service = _get_llm_service()
            # Convert Pydantic models to dicts for the LLM service
            results_dicts = [result.dict() for result in body.results]

            # Get the rendered prompt for the initial event
            prompt = llm_service.render_prompt(
                query=body.query,
                results=results_dicts,
                max_results=body.max_results,
                system_prompt_override=system_prompt_override,
            )

            # Send prompt as first event
            yield f"data: {json.dumps({'type': 'prompt', 'prompt': prompt})}\n\n"

            # Stream the summary tokens
            full_summary = ""
            stream_metadata = {}
            summary_config = body.summary_model_config
            model_key = summary_config.model if summary_config else body.summary_model
            temperature = summary_config.temperature if summary_config else None
            max_tokens = summary_config.max_tokens if summary_config else None
            logger.info(
                "AI summary stream config: model_key=%s, temperature=%s, max_tokens=%s",
                model_key,
                temperature,
                max_tokens,
            )
            async for item in llm_service.stream_ai_summary(
                query=body.query,
                results=results_dicts,
                max_results=body.max_results,
                model_key=model_key,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt_override=system_prompt_override,
            ):
                if isinstance(item, dict):
                    # Metadata dict yielded at the end of the stream
                    stream_metadata = item
                else:
                    full_summary += item
                    yield f"data: {json.dumps({'type': 'token', 'token': item})}\n\n"

            # Send completion event with metadata
            completion_data = {
                "type": "done",
                "query": body.query,
                "results_count": len(body.results),
                "summary": full_summary,
            }
            # Include LangSmith trace URL if available
            if stream_metadata.get("langsmith_trace_url"):
                completion_data["langsmith_trace_url"] = stream_metadata[
                    "langsmith_trace_url"
                ]
            yield f"data: {json.dumps(completion_data)}\n\n"

        except Exception as e:
            logger.error(f"AI summary streaming error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/ai-summary", response_model=AISummaryResponse)
@limiter.limit(RATE_LIMIT_AI)
async def generate_summary(
    request: Request,
    body: AISummaryRequest,
    user=Depends(_resolve_user_dep),
    session=Depends(_get_session_dep),
):
    """
    Generate an AI summary of search results using HuggingFace LLM via LangChain.

    Uses the top N results (default: 20) to generate a concise summary.
    Requires HUGGINGFACE_API_KEY to be set in environment.
    """
    # Resolve group-level summary prompt override (if user is logged in)
    system_prompt_override = await _resolve_summary_prompt(user, session)

    try:
        llm_service = _get_llm_service()
        # Convert Pydantic models to dicts for the LLM service
        results_dicts = [result.dict() for result in body.results]

        # Generate summary using LLM
        summary_config = body.summary_model_config
        model_key = summary_config.model if summary_config else body.summary_model
        temperature = summary_config.temperature if summary_config else None
        max_tokens = summary_config.max_tokens if summary_config else None
        logger.info(
            "AI summary config: model_key=%s, temperature=%s, max_tokens=%s",
            model_key,
            temperature,
            max_tokens,
        )
        summary = await llm_service.generate_ai_summary(
            query=body.query,
            results=results_dicts,
            max_results=body.max_results,
            model_key=model_key,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt_override=system_prompt_override,
        )

        # Get the rendered prompt for debugging/transparency
        prompt = llm_service.render_prompt(
            query=body.query,
            results=results_dicts,
            max_results=body.max_results,
            system_prompt_override=system_prompt_override,
        )

        return AISummaryResponse(
            summary=summary,
            query=body.query,
            results_count=len(body.results),
            prompt=prompt,
        )

    except Exception as e:
        logger.error(f"AI summary generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
