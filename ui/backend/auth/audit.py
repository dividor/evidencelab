"""Audit logging for security-relevant events.

Each call writes a single row to the ``audit_log`` table in a dedicated
session so that audit entries are never lost due to transaction rollbacks
in the calling code.
"""

import logging
import uuid
from typing import Optional

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import AuditLog

logger = logging.getLogger(__name__)


async def write_audit_event(
    event_type: str,
    *,
    user_id: Optional[uuid.UUID] = None,
    user_email: Optional[str] = None,
    ip_address: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Persist an audit log entry.

    Uses its own session so the write succeeds even if the caller's
    transaction is rolled back.
    """
    try:
        async for session in get_async_session():
            entry = AuditLog(
                event_type=event_type,
                user_id=user_id,
                user_email=user_email,
                ip_address=ip_address,
                details=details,
            )
            session.add(entry)
            await session.commit()
    except Exception:
        # Audit logging must never break the request — degrade gracefully
        logger.exception("Failed to write audit event: %s", event_type)
