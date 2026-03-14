"""User management routes — profile, user listing (admin)."""

import logging
import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.audit import write_audit_event
from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import (
    AuditLog,
    OAuthAccount,
    User,
    UserGroup,
    UserGroupMember,
)
from ui.backend.auth.rate_limit import current_request_ip
from ui.backend.auth.schemas import AdminUserCreate, UserCreate, UserRead, UserUpdate
from ui.backend.auth.users import (
    UserManager,
    current_active_user,
    current_superuser,
    fastapi_users,
    get_user_manager,
)
from ui.backend.services.permissions import add_user_to_default_group

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Custom routes MUST be registered before the fastapi-users router so that
# concrete paths like /all and /me/groups are matched before the catch-all
# /{id} route that fastapi-users adds.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Admin: list all users
# ---------------------------------------------------------------------------


@router.get("/all", response_model=List[UserRead], tags=["users"])
async def list_users(
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """List all users (superuser only)."""
    result = await session.execute(select(User).order_by(User.email))
    users = result.unique().scalars().all()
    return users


# ---------------------------------------------------------------------------
# Admin: create a new user (no email verification required)
# ---------------------------------------------------------------------------


@router.post("/create", response_model=UserRead, tags=["users"])
async def admin_create_user(
    body: AdminUserCreate,
    admin: User = Depends(current_superuser),
    user_manager: UserManager = Depends(get_user_manager),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new user account (superuser only).

    The account is created with ``is_verified=True`` so the user can log
    in immediately without email confirmation.  The user is automatically
    added to the default group.

    Unlike self-registration, this bypasses ``on_after_register`` so it
    does **not** send a verification email or depend on SMTP.
    """
    from fastapi_users import exceptions as fu_exceptions

    # Normalise email (lowercase, strip)
    email = body.email.strip().lower()

    # Build a UserCreate schema so validate_password runs (min length, etc.)
    user_schema = UserCreate(
        email=email,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        is_verified=True,
    )

    # Validate password (reuses the same rules as self-registration)
    try:
        await user_manager.validate_password(body.password, user_schema)
    except fu_exceptions.InvalidPasswordException as exc:
        raise HTTPException(status_code=400, detail=exc.reason)

    # Check for duplicate email
    try:
        await user_manager.get_by_email(email)
        raise HTTPException(
            status_code=400, detail="A user with that email already exists."
        )
    except fu_exceptions.UserNotExists:
        pass  # Good — email is available

    # Hash password and create the user directly (skips on_after_register)
    hashed = user_manager.password_helper.hash(body.password)
    new_user = User(
        email=email,
        hashed_password=hashed,
        first_name=body.first_name,
        last_name=body.last_name,
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    session.add(new_user)
    await session.flush()  # assigns new_user.id

    # Add to default group so the user has baseline datasource access
    await add_user_to_default_group(session, new_user.id)

    await session.commit()
    await session.refresh(new_user)

    ip = current_request_ip.get("unknown")
    await write_audit_event(
        "admin_create_user",
        user_id=admin.id,
        user_email=admin.email,
        ip_address=ip,
        details={"created_user_email": email, "created_user_id": str(new_user.id)},
    )
    logger.info("Admin %s created user: %s", admin.email, email)
    return new_user


# ---------------------------------------------------------------------------
# Admin: toggle user flags
# ---------------------------------------------------------------------------


@router.patch("/{user_id}/flags", response_model=UserRead, tags=["users"])
async def update_user_flags(
    user_id: uuid.UUID,
    is_active: bool | None = None,
    is_verified: bool | None = None,
    is_superuser: bool | None = None,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Update user flags (superuser only)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if is_active is not None:
        user.is_active = is_active
    if is_verified is not None:
        user.is_verified = is_verified
    if is_superuser is not None:
        user.is_superuser = is_superuser
    await session.commit()
    await session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Admin: delete a user (cascade)
# ---------------------------------------------------------------------------


@router.delete("/{user_id}", tags=["users"])
async def admin_delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a user and all associated data (superuser only)."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user_email = user.email

    # Remove group memberships
    await session.execute(
        delete(UserGroupMember).where(UserGroupMember.user_id == user_id)
    )
    # Remove OAuth links
    await session.execute(delete(OAuthAccount).where(OAuthAccount.user_id == user_id))
    # Anonymise audit log entries
    await session.execute(
        update(AuditLog).where(AuditLog.user_id == user_id).values(user_id=None)
    )
    # Delete the user record
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()

    logger.info("Admin deleted user: %s (%s)", user_email, user_id)
    return {"detail": f"User {user_email} deleted."}


# ---------------------------------------------------------------------------
# Current user: my groups
# ---------------------------------------------------------------------------


@router.get("/me/groups", tags=["users"])
async def get_my_groups(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return groups the current user belongs to."""
    stmt = (
        select(UserGroup)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .where(UserGroupMember.user_id == user.id)
        .order_by(UserGroup.name)
    )
    result = await session.execute(stmt)
    groups = result.scalars().all()
    return [
        {
            "id": str(g.id),
            "name": g.name,
            "description": g.description,
            "search_settings": g.search_settings,
        }
        for g in groups
    ]


def _merge_group_settings(groups: list) -> dict:
    """Merge search_settings from multiple groups (first non-null per key wins).

    Groups are expected to be ordered by name ASC so that the "Default" group
    has lowest priority (comes first alphabetically for most custom group names).
    """
    merged: dict = {}
    for group in groups:
        settings = group.search_settings
        if not settings:
            continue
        for key, value in settings.items():
            if key not in merged:
                merged[key] = value
    return merged


@router.get("/me/effective-settings", tags=["users"])
async def get_effective_settings(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return merged search settings from all of the current user's groups.

    Settings are merged across groups — first non-null value per key wins,
    ordered by group name ASC (so "Default" group is lowest priority).
    Returns only the overridden keys; empty dict means no overrides.
    """
    stmt = (
        select(UserGroup)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .where(UserGroupMember.user_id == user.id)
        .order_by(UserGroup.name)
    )
    result = await session.execute(stmt)
    groups = result.scalars().all()
    return _merge_group_settings(groups)


# ---------------------------------------------------------------------------
# Self-service account deletion
# ---------------------------------------------------------------------------


@router.delete("/me/account", tags=["users"])
async def delete_my_account(
    response: Response,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Permanently delete the current user's account and associated data.

    This removes:
    - Group memberships
    - OAuth account links
    - The user record itself

    Audit log entries are anonymised (user_id set to NULL) so security
    records are preserved without retaining personal data.
    """
    ip = current_request_ip.get("unknown")
    user_id = user.id
    user_email = user.email

    # Write the audit event *before* deleting so we capture who deleted
    await write_audit_event(
        "account_deleted",
        user_id=user_id,
        user_email=user_email,
        ip_address=ip,
    )

    # Anonymise audit log entries for this user
    await session.execute(
        update(AuditLog).where(AuditLog.user_id == user_id).values(user_id=None)
    )

    # Remove group memberships
    await session.execute(
        delete(UserGroupMember).where(UserGroupMember.user_id == user_id)
    )

    # Remove OAuth links
    await session.execute(delete(OAuthAccount).where(OAuthAccount.user_id == user_id))

    # Delete the user record
    await session.execute(delete(User).where(User.id == user_id))

    await session.commit()

    logger.info("Account deleted: %s (%s)", user_email, user_id)

    # Clear auth and CSRF cookies so the browser is fully logged out
    _cookie_secure = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() != "false"
    response.delete_cookie(
        "evidencelab_auth",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure,
    )
    response.delete_cookie(
        "evidencelab_csrf",
        samesite="lax",
        secure=_cookie_secure,
        path="/",
    )

    return {"detail": "Account deleted successfully."}


# ---------------------------------------------------------------------------
# fastapi-users built-in routes (GET /me, PATCH /me, DELETE /{id}, etc.)
# MUST come last so the catch-all /{id} doesn't shadow our custom routes.
# ---------------------------------------------------------------------------

router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    tags=["users"],
)
