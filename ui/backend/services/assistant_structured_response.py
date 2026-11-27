"""Validate an Assistant reply against the requested schema and request a correction if needed."""

import logging
import re
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import TypeAdapter, ValidationError

from ui.backend.services.assistant_grounding import (
    InvalidAssistantResponse,
    TruncatedAssistantResponse,
)
from utils.llm_factory import message_text

logger = logging.getLogger(__name__)
_Result = TypeVar("_Result")
_JSON_FENCE = re.compile(r"`{3}(?:json)?\s*(.*?)\s*`{3}", re.DOTALL | re.IGNORECASE)


async def request_structured_response(
    model,
    system,
    prompt,
    history,
    config,
    schema: TypeAdapter[_Result],
    request_template,
) -> _Result:
    messages = [SystemMessage(content=system), *history]
    request = prompt
    for _ in range(2):
        response = await model.ainvoke(
            [*messages, HumanMessage(content=request)], config=config
        )
        raw = message_text(response).strip()
        fenced = _JSON_FENCE.search(raw)
        try:
            return schema.validate_json(fenced[1] if fenced else raw)
        except ValidationError as exc:
            errors = [
                (error["loc"], error["type"])
                for error in exc.errors(
                    include_input=False, include_context=False, include_url=False
                )
            ]
            logger.warning(
                "Invalid structured Assistant response (stop=%s, output_tokens=%s): %s",
                response.response_metadata.get("finish_reason"),
                (getattr(response, "usage_metadata", None) or {}).get("output_tokens"),
                errors,
            )
            request = (
                prompt
                + "\n\n"
                + request_template.render(
                    stage="retry_plan",
                    validation_errors=errors[:12],
                    reply_schema=schema.json_schema(),
                )
            )
    if response.response_metadata.get("finish_reason") == "length":
        raise TruncatedAssistantResponse(
            "The structured response reached its output limit"
        )
    raise InvalidAssistantResponse(
        "The Assistant model could not produce a valid structured response"
    )
