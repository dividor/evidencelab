"""
Research Assistant API routes.

Provides endpoints for:
- Streaming research assistant chat via SSE
- Conversation thread CRUD (for authenticated users)
"""

import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ui.backend.auth.schemas import (
    AssistantChatRequest,
    ConversationThreadListItem,
    ConversationThreadRead,
)
from ui.backend.services.assistant_service import stream_research_response
from ui.backend.utils.app_limits import get_rate_limits, limiter

logger = logging.getLogger(__name__)

_, _, RATE_LIMIT_AI = get_rate_limits()
router = APIRouter()

# ---------------------------------------------------------------------------
# Conditional user-module imports (same pattern as summary.py)
# ---------------------------------------------------------------------------
_UM_RAW = os.environ.get("USER_MODULE", "off").lower()
_USER_MODULE = _UM_RAW not in ("off", "0", "false", "no")

if _USER_MODULE:
    from ui.backend.auth.db import get_async_session as _get_session_dep
    from ui.backend.auth.models import ConversationMessage, ConversationThread
    from ui.backend.auth.users import current_active_user as _require_user_dep
    from ui.backend.auth.users import optional_current_user as _resolve_user_dep
else:

    async def _noop_user():
        return None

    async def _noop_session():
        return None

    _resolve_user_dep = _noop_user
    _require_user_dep = _noop_user
    _get_session_dep = _noop_session


# ---------------------------------------------------------------------------
# Streaming chat endpoint
# ---------------------------------------------------------------------------


@router.post("/assistant/chat/stream")
@limiter.limit(RATE_LIMIT_AI)
async def stream_assistant_chat(
    request: Request,
    body: AssistantChatRequest,
    user=Depends(_resolve_user_dep),
    session=Depends(_get_session_dep),
):
    """
    Stream a research assistant response via Server-Sent Events.

    The agent performs: plan -> search -> synthesize -> reflect
    in a loop, streaming progress events at each phase.
    """
    # Resolve model config from request
    model_config = body.assistant_model_config
    model_key = model_config.model if model_config else None
    temperature = model_config.temperature if model_config else None
    max_tokens = model_config.max_tokens if model_config else None

    # Load conversation history if thread_id provided and user authenticated
    conversation_messages = []
    if body.thread_id and _USER_MODULE and user and session:
        try:
            thread_id = uuid.UUID(body.thread_id)
            stmt = (
                select(ConversationMessage)
                .where(
                    ConversationMessage.thread_id == thread_id,
                )
                .order_by(ConversationMessage.created_at)
            )
            result = await session.execute(stmt)
            msgs = result.scalars().all()
            conversation_messages = [
                {"role": m.role, "content": m.content} for m in msgs
            ]
        except Exception as exc:
            logger.warning("Failed to load thread history: %s", exc)

    async def event_generator():
        """Stream assistant events as SSE."""
        thread_id = body.thread_id
        try:
            async for event in stream_research_response(
                query=body.query,
                data_source=body.data_source,
                model_key=model_key,
                temperature=temperature,
                max_tokens=max_tokens,
                max_iterations=3,
                conversation_messages=conversation_messages,
            ):
                # Persist messages on completion if user is authenticated
                if event.get("type") == "done" and _USER_MODULE and user and session:
                    try:
                        thread_id = await _persist_conversation(
                            session=session,
                            user=user,
                            thread_id=body.thread_id,
                            query=body.query,
                            data_source=body.data_source,
                            synthesis=event.get("synthesis", ""),
                            sources=event.get("sources"),
                        )
                        event["threadId"] = str(thread_id)
                    except Exception as exc:
                        logger.warning("Failed to persist conversation: %s", exc)

                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            logger.error("Assistant stream error: %s", e, exc_info=True)
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


async def _persist_conversation(
    session,
    user,
    thread_id,
    query,
    data_source,
    synthesis,
    sources,
):
    """Persist user and assistant messages to a conversation thread."""
    # Create or get thread
    if thread_id:
        tid = uuid.UUID(thread_id)
    else:
        # Create new thread with query as title (truncated)
        title = query[:200] if len(query) > 200 else query
        thread = ConversationThread(
            user_id=user.id,
            title=title,
            data_source=data_source,
        )
        session.add(thread)
        await session.flush()
        tid = thread.id

    # Save user message
    user_msg = ConversationMessage(
        thread_id=tid,
        role="user",
        content=query,
    )
    session.add(user_msg)

    # Save assistant message
    assistant_msg = ConversationMessage(
        thread_id=tid,
        role="assistant",
        content=synthesis or "",
        sources={"citations": sources} if sources else None,
    )
    session.add(assistant_msg)

    await session.commit()
    return tid


# ---------------------------------------------------------------------------
# Thread CRUD endpoints (require authentication)
# ---------------------------------------------------------------------------


@router.get("/assistant/threads")
async def list_threads(
    user=Depends(_require_user_dep),
    session=Depends(_get_session_dep),
):
    """List conversation threads for the current user."""
    if not _USER_MODULE or not user or not session:
        raise HTTPException(status_code=401, detail="Authentication required")

    stmt = (
        select(
            ConversationThread.id,
            ConversationThread.title,
            ConversationThread.data_source,
            ConversationThread.created_at,
            ConversationThread.updated_at,
            func.count(ConversationMessage.id).label("message_count"),
        )
        .outerjoin(
            ConversationMessage,
            ConversationMessage.thread_id == ConversationThread.id,
        )
        .where(ConversationThread.user_id == user.id)
        .group_by(ConversationThread.id)
        .order_by(ConversationThread.updated_at.desc())
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        ConversationThreadListItem(
            id=row.id,
            title=row.title,
            data_source=row.data_source,
            message_count=row.message_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/assistant/threads/{thread_id}")
async def get_thread(
    thread_id: uuid.UUID,
    user=Depends(_require_user_dep),
    session=Depends(_get_session_dep),
):
    """Get a conversation thread with all messages."""
    if not _USER_MODULE or not user or not session:
        raise HTTPException(status_code=401, detail="Authentication required")

    stmt = (
        select(ConversationThread)
        .options(selectinload(ConversationThread.messages))
        .where(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == user.id,
        )
    )

    result = await session.execute(stmt)
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    return ConversationThreadRead.model_validate(thread)


@router.delete("/assistant/threads/{thread_id}")
async def delete_thread(
    thread_id: uuid.UUID,
    user=Depends(_require_user_dep),
    session=Depends(_get_session_dep),
):
    """Delete a conversation thread and all its messages."""
    if not _USER_MODULE or not user or not session:
        raise HTTPException(status_code=401, detail="Authentication required")

    stmt = select(ConversationThread).where(
        ConversationThread.id == thread_id,
        ConversationThread.user_id == user.id,
    )

    result = await session.execute(stmt)
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    await session.delete(thread)
    await session.commit()

    return {"status": "deleted", "id": str(thread_id)}
