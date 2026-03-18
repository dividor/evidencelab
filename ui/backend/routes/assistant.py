"""
Research Assistant API routes.

Provides endpoints for:
- Streaming research assistant chat via SSE
- Conversation thread CRUD (for authenticated users)
"""

import asyncio
import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ui.backend.auth.schemas import AssistantChatRequest, ThreadRenameRequest
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
    from ui.backend.auth.models import (
        ConversationMessage,
        ConversationThread,
        UserGroup,
        UserGroupMember,
    )
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
# Group prompt resolution
# ---------------------------------------------------------------------------


async def _resolve_group_prompt(user, session) -> str | None:
    """Return the first non-null summary_prompt from the user's groups.

    This is the same logic used by the /ai-summary endpoint.  The group
    prompt provides domain-specific instructions that supplement the
    assistant's built-in system prompt.
    """
    if not _USER_MODULE or user is None or session is None:
        return None
    try:
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
            logger.info(
                "Resolved group prompt for assistant: group=%s (default=%s), len=%d",
                group_name,
                is_default,
                len(prompt),
            )
            return prompt
    except Exception as exc:
        logger.warning("Failed to resolve group prompt: %s", exc)
    return None


# ---------------------------------------------------------------------------
# SSE heartbeat helper
# ---------------------------------------------------------------------------
_STREAM_STOP = object()
_HEARTBEAT_INTERVAL = 15  # seconds


async def _anext_or_stop(ait):
    """Await next item from async iterator, return sentinel at end."""
    try:
        return await ait.__anext__()
    except StopAsyncIteration:
        return _STREAM_STOP


# ---------------------------------------------------------------------------
# Streaming chat helpers
# ---------------------------------------------------------------------------


def _resolve_model_config(body: AssistantChatRequest):
    """Extract model key, temperature, max_tokens from the request."""
    cfg = body.assistant_model_config
    return (
        cfg.model if cfg else None,
        cfg.temperature if cfg else None,
        cfg.max_tokens if cfg else None,
    )


async def _load_conversation_history(body, user, session):
    """Load prior messages for a thread, returning a list of dicts."""
    if not (body.thread_id and _USER_MODULE and user and session):
        return []
    try:
        thread_id = uuid.UUID(body.thread_id)
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.thread_id == thread_id)
            .order_by(ConversationMessage.created_at)
        )
        result = await session.execute(stmt)
        msgs = result.scalars().all()
        return [{"role": m.role, "content": m.content} for m in msgs]
    except Exception as exc:
        logger.warning("Failed to load thread history: %s", exc)
        return []


async def _stream_with_heartbeat(ait):
    """Yield events from *ait*, inserting SSE heartbeat comments on idle."""
    task = None
    try:
        while True:
            task = asyncio.create_task(_anext_or_stop(ait))
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=_HEARTBEAT_INTERVAL)
                if not done:
                    yield None  # caller sends heartbeat
            event = task.result()
            task = None
            if event is _STREAM_STOP:
                break
            yield event
    finally:
        if task and not task.done():
            task.cancel()


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
    model_key, temperature, max_tokens = _resolve_model_config(body)
    conversation_messages = await _load_conversation_history(body, user, session)
    # For unauthenticated users (no thread persistence), use client-sent history
    if not conversation_messages and body.conversation_history:
        conversation_messages = body.conversation_history
    group_prompt = await _resolve_group_prompt(user, session)

    async def event_generator():
        thread_id = body.thread_id
        last_synthesis = ""
        last_sources = None
        try:
            search_kwargs = (
                body.search_settings.model_dump(exclude_none=True)
                if body.search_settings
                else None
            )
            ait = stream_research_response(
                query=body.query,
                data_source=body.data_source,
                model_key=model_key,
                temperature=temperature,
                max_tokens=max_tokens,
                max_iterations=3,
                conversation_messages=conversation_messages,
                reranker_model=body.reranker_model,
                search_settings=search_kwargs,
                system_prompt_override=group_prompt,
                deep_research=body.deep_research,
            ).__aiter__()

            async for event in _stream_with_heartbeat(ait):
                if event is None:
                    yield ": heartbeat\n\n"
                    continue
                # Track synthesis text and sources for persistence
                etype = event.get("type")
                if etype == "token":
                    last_synthesis = event.get("token", "")
                elif etype == "sources":
                    last_sources = event.get("sources")
                elif _should_persist(event, user, session):
                    persist_event = {
                        **event,
                        "synthesis": last_synthesis,
                        "sources": last_sources,
                    }
                    thread_id = await _try_persist(
                        session, user, body, persist_event, thread_id
                    )
                    if "threadId" in persist_event:
                        event["threadId"] = persist_event["threadId"]
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


def _should_persist(event, user, session) -> bool:
    """Check if this event should trigger conversation persistence."""
    return (
        event.get("type") == "done"
        and _USER_MODULE
        and user is not None
        and session is not None
    )


async def _try_persist(session, user, body, event, thread_id):
    """Attempt to persist conversation, returning updated thread_id."""
    try:
        tid = await _persist_conversation(
            session=session,
            user=user,
            thread_id=body.thread_id,
            query=body.query,
            data_source=body.data_source,
            synthesis=event.get("synthesis", ""),
            sources=event.get("sources"),
        )
        event["threadId"] = str(tid)
        return tid
    except Exception as exc:
        logger.warning("Failed to persist conversation: %s", exc)
        return thread_id


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
        {
            "id": str(row.id),
            "title": row.title,
            "dataSource": row.data_source,
            "messageCount": row.message_count,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }
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

    sorted_msgs = sorted(thread.messages, key=lambda m: m.created_at)
    return {
        "id": str(thread.id),
        "title": thread.title,
        "dataSource": thread.data_source,
        "createdAt": thread.created_at.isoformat(),
        "updatedAt": thread.updated_at.isoformat(),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "sources": m.sources,
                "createdAt": m.created_at.isoformat(),
            }
            for m in sorted_msgs
        ],
    }


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


@router.patch("/assistant/threads/{thread_id}")
async def rename_thread(
    thread_id: uuid.UUID,
    body: ThreadRenameRequest,
    user=Depends(_require_user_dep),
    session=Depends(_get_session_dep),
):
    """Rename a conversation thread."""
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

    thread.title = body.title
    await session.commit()

    return {"status": "renamed", "id": str(thread_id), "title": body.title}
