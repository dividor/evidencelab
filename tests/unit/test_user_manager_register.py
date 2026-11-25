"""What happens after an account is created (UserManager.on_after_register).

Email sign-up creates an unverified account and sends a verification email.
Google and Microsoft sign-ins create the account already verified; asking them
to verify again raised UserAlreadyVerified, which failed a new person's first
Google or Microsoft sign-in.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi_users import exceptions as fu_exceptions

from ui.backend.auth import users as users_module
from ui.backend.auth.users import UserManager

pytestmark = pytest.mark.unit


async def _one_session():
    yield MagicMock()


def _user(verified: bool):
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        email="person@example.org",
        is_verified=verified,
        is_active=True,
    )


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.delenv("DISABLE_EMAIL_CONFIRMATION", raising=False)
    with patch.object(users_module, "get_async_session", _one_session), patch.object(
        users_module, "add_user_to_default_group", new_callable=AsyncMock
    ) as group, patch.object(
        users_module, "write_audit_event", new_callable=AsyncMock
    ) as audit:
        yield UserManager(MagicMock()), group, audit


@pytest.mark.asyncio
async def test_on_after_register_when_verified_by_provider_then_no_verify_email(
    manager,
):
    user_manager, group, audit = manager
    user_manager.on_after_request_verify = AsyncMock()

    await user_manager.on_after_register(_user(verified=True))

    user_manager.on_after_request_verify.assert_not_called()
    group.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_after_register_when_email_sign_up_then_sends_verify_email(manager):
    user_manager, group, audit = manager
    user_manager.on_after_request_verify = AsyncMock()

    await user_manager.on_after_register(_user(verified=False))

    user_manager.on_after_request_verify.assert_awaited_once()
    group.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_verify_when_already_verified_then_raises(manager):
    """Why the check is needed: fastapi-users refuses a verified account."""
    user_manager, _, _ = manager
    with pytest.raises(fu_exceptions.UserAlreadyVerified):
        await user_manager.request_verify(_user(verified=True))
