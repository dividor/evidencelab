"""Which data source a request works on when it names none."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

from pipeline.db import config as db_config
from pipeline.db.config import resolve_data_source
from ui.backend.utils import app_state

ONE = {"datasources": {"WFP Evaluation Reports": {"data_subdir": "wfp"}}}
TWO = {
    "datasources": {
        "UN Reports": {"data_subdir": "uneg"},
        "World Bank": {"data_subdir": "worldbank"},
    }
}


def _config(config):
    return patch.object(db_config, "load_datasources_config", return_value=config)


@pytest.mark.unit
class TestResolveDataSource:
    def test_resolve_when_named_then_kept_as_named(self):
        with _config(ONE):
            assert resolve_data_source("other") == "other"

    @pytest.mark.parametrize("missing", [None, ""])
    def test_resolve_when_one_configured_then_uses_it(self, missing):
        with _config(ONE):
            assert resolve_data_source(missing) == "wfp"

    def test_resolve_when_one_configured_then_setting_cannot_override(self):
        with _config(ONE), patch.object(db_config, "DEFAULT_DATA_SOURCE", "uneg"):
            assert resolve_data_source(None) == "wfp"

    def test_resolve_when_several_and_setting_then_uses_setting(self):
        with _config(TWO), patch.object(db_config, "DEFAULT_DATA_SOURCE", "worldbank"):
            assert resolve_data_source(None) == "worldbank"

    def test_resolve_when_several_and_no_setting_then_raises(self):
        with _config(TWO), patch.object(db_config, "DEFAULT_DATA_SOURCE", None):
            with pytest.raises(ValueError, match="Invalid data_source: none given"):
                resolve_data_source(None)

    def test_resolve_when_none_configured_then_raises(self):
        with _config({}), patch.object(db_config, "DEFAULT_DATA_SOURCE", None):
            with pytest.raises(ValueError, match="Invalid data_source"):
                resolve_data_source(None)

    def test_validate_when_source_from_another_deployment_then_rejected(self):
        with _config(ONE), patch.object(
            app_state, "_get_valid_data_sources", return_value={"wfp"}
        ):
            with pytest.raises(ValueError, match="Invalid data_source: uneg"):
                app_state.validate_data_source("uneg")

    def test_validate_when_none_named_then_the_only_one(self):
        with _config(ONE), patch.object(
            app_state, "_get_valid_data_sources", return_value={"wfp"}
        ):
            assert app_state.validate_data_source(None) == "wfp"


class _User:
    id = "user-1"
    is_superuser = False


@pytest.mark.unit
class TestEnsureDataSourceAccess:
    @pytest.fixture
    def permissions(self):
        from ui.backend.services import permissions

        return permissions

    async def _check(self, permissions, user, allowed, source="wfp"):
        with patch.object(
            permissions, "get_user_datasource_keys", AsyncMock(return_value=allowed)
        ), patch.object(permissions, "load_datasources_config", return_value=ONE):
            await permissions.ensure_data_source_access(None, user, source)

    @pytest.mark.asyncio
    async def test_access_when_group_grants_it_then_allowed(self, permissions):
        await self._check(permissions, _User(), {"WFP Evaluation Reports"})

    @pytest.mark.asyncio
    async def test_access_when_no_grants_then_refused(self, permissions):
        with pytest.raises(HTTPException) as err:
            await self._check(permissions, _User(), set())
        assert err.value.status_code == 403

    @pytest.mark.asyncio
    async def test_access_when_superuser_then_allowed(self, permissions):
        user = _User()
        user.is_superuser = True
        await self._check(permissions, user, set())

    @pytest.mark.asyncio
    async def test_access_when_signed_out_then_allowed(self, permissions):
        await self._check(permissions, None, set())


@pytest.mark.unit
class TestChatDataSource:
    """The research request runs on the settled data source, or not at all."""

    async def _chat(self, body):
        from starlette.requests import Request

        from ui.backend.routes.assistant import stream_assistant_chat

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/assistant/chat/stream",
                "headers": [],
                "client": ("1.1.1.1", 1),
                "app": None,
            }
        )
        return await stream_assistant_chat(
            request=request, body=body, user=None, session=None
        )

    @pytest.mark.asyncio
    async def test_chat_when_no_source_then_researches_the_only_one(self):
        from ui.backend.auth.schemas import AssistantChatRequest
        from ui.backend.utils.app_limits import limiter

        limiter.enabled = False

        async def fake_stream(**kwargs):
            yield {"type": "done", "data_source": kwargs["data_source"]}

        with _config(ONE), patch.object(
            app_state, "_get_valid_data_sources", return_value={"wfp"}
        ), patch("ui.backend.routes.assistant.stream_research_response", fake_stream):
            response = await self._chat(AssistantChatRequest(query="q"))
            chunks = [c async for c in response.body_iterator]
        assert any('"data_source": "wfp"' in c for c in chunks)

    @pytest.mark.asyncio
    async def test_chat_when_source_not_in_this_deployment_then_rejected(self):
        from ui.backend.auth.schemas import AssistantChatRequest
        from ui.backend.utils.app_limits import limiter

        limiter.enabled = False
        with _config(ONE), patch.object(
            app_state, "_get_valid_data_sources", return_value={"wfp"}
        ):
            with pytest.raises(ValueError, match="Invalid data_source: uneg"):
                await self._chat(AssistantChatRequest(query="q", data_source="uneg"))


@pytest.mark.unit
class TestRejectedRequestLogging:
    @pytest.mark.asyncio
    async def test_422_when_logged_then_names_fields_not_values(self):
        from ui.backend import main as main_module

        guidance_text = "private guidance text"
        exc = RequestValidationError(
            [
                {
                    "loc": ("body", "brief_section", "instructions"),
                    "type": "string_too_long",
                    "msg": "too long",
                    "input": guidance_text,
                }
            ]
        )
        request = SimpleNamespace(
            method="POST", url=SimpleNamespace(path="/assistant/chat/stream")
        )
        with patch.object(main_module, "_main_logger") as logger:
            response = await main_module.request_validation_handler(request, exc)
        assert response.status_code == 422
        logged = str(logger.warning.call_args)
        assert "body.brief_section.instructions" in logged
        assert "string_too_long" in logged
        assert guidance_text not in logged
