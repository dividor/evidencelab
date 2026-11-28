from unittest.mock import AsyncMock, Mock

import pytest
from botocore.exceptions import ClientError
from langchain_core.messages import AIMessage
from pydantic import TypeAdapter

from ui.backend.services.assistant_grounding import InvalidAssistantResponse
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.assistant_structured_response import (
    request_structured_response,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def rejected_tool():
    return ClientError(
        {
            "Error": {
                "Code": "ModelErrorException",
                "Message": "Model produced invalid sequence as part of ToolUse.",
            }
        },
        "Converse",
    )


def _model(*responses):
    model = Mock()
    invoke = AsyncMock(side_effect=responses)
    model.bind_tools.return_value.ainvoke = invoke
    return model, invoke


async def _request(model):
    return await request_structured_response(
        model,
        "Select relevant excerpts.",
        "Select from excerpts 1 and 2.",
        [],
        {},
        TypeAdapter(list[int]),
        assistant_prompt_templates.get_template("assistant_research_request.j2"),
    )


@pytest.mark.asyncio
async def test_bedrock_rejected_tool_use_gets_the_format_correction(rejected_tool):
    corrected = AIMessage(
        content="",
        tool_calls=[{"name": "submit_result", "args": {"result": [2]}, "id": "tool"}],
    )
    model, invoke = _model(rejected_tool, corrected)

    assert await _request(model) == [2]
    assert invoke.await_count == 2
    assert "malformed_tool_use" in invoke.await_args.args[0][-1].content


@pytest.mark.asyncio
async def test_bedrock_rejects_tool_use_twice_then_reports_invalid_response(
    rejected_tool,
):
    model, invoke = _model(rejected_tool, rejected_tool)

    with pytest.raises(InvalidAssistantResponse):
        await _request(model)

    assert invoke.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["ModelErrorException", "AccessDeniedException"])
async def test_other_bedrock_errors_keep_the_provider_error(code):
    error = ClientError(
        {"Error": {"Code": code, "Message": "Other provider failure."}}, "Converse"
    )
    model, invoke = _model(error)

    with pytest.raises(ClientError) as failure:
        await _request(model)

    assert failure.value is error
    invoke.assert_awaited_once()
