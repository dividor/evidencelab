"""Validate an Assistant reply against the requested schema and request a correction if needed."""

import logging
from typing import TypeVar

from botocore.exceptions import ClientError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import TypeAdapter, ValidationError

from ui.backend.services.assistant_grounding import (
    InvalidAssistantResponse,
    MalformedAssistantToolResponse,
    TruncatedAssistantResponse,
)

logger = logging.getLogger(__name__)
_Result = TypeVar("_Result")
_RESULT_TOOL = "submit_result"


def _bedrock_rejected_tool_result(error: ClientError) -> bool:
    details = error.response.get("Error", {})
    return (
        error.operation_name == "Converse"
        and details.get("Code") == "ModelErrorException"
        and "invalid sequence as part of ToolUse" in details.get("Message", "")
    )


def _result_parameters(schema: dict) -> dict:
    # Tool arguments must be an object, even when the result is a JSON array.
    result = dict(schema)
    definitions = result.pop("$defs", {})
    parameters = {
        "type": "object",
        "properties": {"result": result},
        "required": ["result"],
        "additionalProperties": False,
    }
    if definitions:
        parameters["$defs"] = definitions
    return parameters


def _stop_reason(response: AIMessage) -> str:
    metadata = response.response_metadata
    return str(
        metadata.get("finish_reason") or metadata.get("stopReason") or ""
    ).lower()


def _result_errors(response: AIMessage, schema: TypeAdapter[_Result], wrapped: bool):
    calls = response.tool_calls
    if response.invalid_tool_calls or len(calls) != 1:
        return None, [((), "expected_one_result_tool_call")]
    call = calls[0]
    if call["name"] != _RESULT_TOOL or (wrapped and call["args"].keys() != {"result"}):
        return None, [((), "invalid_result_tool_arguments")]
    arguments = call["args"]
    try:
        return schema.validate_python(arguments["result"] if wrapped else arguments), []
    except ValidationError as exc:
        return None, [
            (error["loc"], error["type"])
            for error in exc.errors(
                include_input=False, include_context=False, include_url=False
            )
        ]


async def request_structured_response(
    model,
    system,
    prompt,
    history,
    config,
    schema: TypeAdapter[_Result],
    request_template,
) -> _Result:
    reply_schema = schema.json_schema()
    wrapped = reply_schema.get("type") != "object"
    tool = {
        "name": _RESULT_TOOL,
        "description": "Return the requested structured result.",
        "parameters": _result_parameters(reply_schema) if wrapped else reply_schema,
    }
    structured_model = model.bind_tools([tool], tool_choice=_RESULT_TOOL)
    tool_instruction = (
        "Call submit_result once with the requested JSON as its arguments."
    )
    if wrapped:
        tool_instruction = (
            "Call submit_result once. "
            "Put the requested JSON value in its result argument."
        )
    messages = [SystemMessage(content=f"{system}\n\n{tool_instruction}"), *history]
    request = prompt
    for _ in range(2):
        try:
            response = await structured_model.ainvoke(
                [*messages, HumanMessage(content=request)], config=config
            )
        except ClientError as error:
            if not _bedrock_rejected_tool_result(error):
                raise
            stop_reason = "malformed_tool_use"
            output_tokens = None
            errors = [((), "malformed_tool_use")]
        else:
            stop_reason = _stop_reason(response)
            output_tokens = (response.usage_metadata or {}).get("output_tokens")
            result, errors = _result_errors(response, schema, wrapped)
            if not errors:
                return result
        logger.warning(
            "Invalid structured Assistant response (stop=%s, output_tokens=%s): %s",
            stop_reason,
            output_tokens,
            errors,
        )
        request = (
            prompt
            + "\n\n"
            + request_template.render(
                stage="retry_plan",
                validation_errors=errors[:12],
                reply_schema=reply_schema,
            )
        )
    if stop_reason in {"length", "max_tokens"}:
        raise TruncatedAssistantResponse(
            "The structured response reached its output limit"
        )
    if stop_reason == "malformed_tool_use":
        raise MalformedAssistantToolResponse("The model returned a malformed tool call")
    raise InvalidAssistantResponse(
        "The Assistant model could not produce a valid structured response"
    )
