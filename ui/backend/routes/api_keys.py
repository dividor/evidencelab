"""API key management routes — generate, list, revoke (admin only)."""

import hashlib
import logging
import secrets
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.api_key_cache import invalidate_cache
from ui.backend.auth.audit import write_audit_event
from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import ApiKey, User
from ui.backend.auth.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from ui.backend.auth.users import current_superuser
from ui.backend.utils.app_limits import limiter
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter()


def _key_to_read(key: ApiKey, email: str | None = None) -> ApiKeyRead:
    """Convert an ApiKey ORM object to an ApiKeyRead schema.

    Decrypts ``key_value`` if it was stored encrypted.  Legacy plaintext
    values (pre-encryption) are returned as-is with a warning logged.
    """
    decrypted: str | None = None
    if key.key_value:
        try:
            decrypted = decrypt_value(key.key_value)
        except Exception:
            logger.error(
                "Failed to decrypt key_value for key id=%s — "
                "value may be corrupted. Returning None.",
                key.id,
            )
    return ApiKeyRead(
        id=key.id,
        label=key.label,
        key_prefix=key.key_prefix,
        key_value=decrypted,
        is_active=key.is_active,
        created_at=key.created_at,
        created_by_email=email,
        last_used_at=key.last_used_at,
    )


@router.get("/", response_model=List[ApiKeyRead])
async def list_api_keys(
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> List[ApiKeyRead]:
    """List all API keys (admin only)."""
    stmt = (
        select(ApiKey, User.email)
        .outerjoin(User, ApiKey.created_by_user_id == User.id)
        .order_by(ApiKey.created_at.desc())
    )
    result = await session.execute(stmt)
    return [_key_to_read(row[0], row[1]) for row in result.all()]


@router.post("/", response_model=ApiKeyCreated, status_code=201)
@limiter.limit("10/hour")
async def create_api_key(
    request: Request,
    body: ApiKeyCreate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> ApiKeyCreated:
    """Generate a new API key (admin only). The full key is returned once."""
    raw_key = "el_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    # Derive prefix from the key's hash — NOT from the key itself — so the
    # displayed prefix cannot be used to narrow a brute-force search space.
    # 7 hex chars gives 28-bit uniqueness; collision probability is negligible
    # for the small number of keys any deployment will have.
    key_prefix = "el_" + key_hash[:7]

    api_key = ApiKey(
        label=body.label,
        key_hash=key_hash,
        key_prefix=key_prefix,
        key_value=encrypt_value(raw_key),
        created_by_user_id=admin.id,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    invalidate_cache()

    await write_audit_event(
        "api_key_created",
        user_id=admin.id,
        user_email=admin.email,
        details={"label": body.label, "key_prefix": key_prefix},
    )

    return ApiKeyCreated(
        id=api_key.id,
        label=api_key.label,
        key_prefix=api_key.key_prefix,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        created_by_email=admin.email,
        last_used_at=None,
        key=raw_key,
    )


@router.get("/legacy")
async def get_legacy_key(
    admin: User = Depends(current_superuser),
) -> dict:
    """Return the legacy API_KEY env-var value (admin only).

    This key is stored in plaintext in the environment and is safe to
    expose to superusers for copy-paste convenience.
    """
    from ui.backend.auth.api_key_verify import API_KEY

    if not API_KEY:
        return {"key": None}
    return {"key": API_KEY}


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Revoke and delete an API key (admin only)."""
    result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalars().first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    label = api_key.label
    prefix = api_key.key_prefix
    await session.delete(api_key)
    await session.commit()
    invalidate_cache()

    await write_audit_event(
        "api_key_deleted",
        user_id=admin.id,
        user_email=admin.email,
        details={"label": label, "key_prefix": prefix},
    )

    return {"detail": "API key revoked."}
