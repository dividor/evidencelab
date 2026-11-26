"""Validated group overrides for the Assistant workflow."""

from pathlib import Path
from typing import Annotated, Optional, Sequence

from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from pipeline.db import config as db_config
from ui.backend.services.group_settings import ASSISTANT_SETTINGS_KEY
from ui.backend.utils.llm_request_limits import check_requested_llm, max_output_tokens

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, max_length=12000)]
assistant_prompt_templates = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[3] / "prompts")),
    autoescape=True,
)


class AssistantSettings(BaseModel):
    """Overrides saved inside a group's search settings."""

    model_config = ConfigDict(extra="forbid", strict=True)

    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0, le=1)
    maxTokens: Optional[int] = Field(None, ge=1)
    planningPrompt: Optional[Prompt] = None
    answerPrompt: Optional[Prompt] = None
    planningInstructions: Optional[Prompt] = None
    answerInstructions: Optional[Prompt] = None
    searches: Optional[int] = Field(None, ge=1, le=20)
    searchesPerStream: Optional[int] = Field(None, ge=1, le=6)
    deepSearches: Optional[int] = Field(None, ge=1, le=20)
    deepSearchesPerStream: Optional[int] = Field(None, ge=1, le=6)
    deepResearchByDefault: Optional[bool] = None

    def model_options(
        self,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> tuple[Optional[str], Optional[float], Optional[int]]:
        """Resolve the group's choice after the request itself has been validated."""
        if self.model:
            if self.model not in db_config.SUPPORTED_LLMS:
                raise HTTPException(
                    status_code=409,
                    detail="The group’s Assistant model is no longer available. "
                    "Choose another in Group Settings → Assistant.",
                )
            model = self.model
            if max_tokens is not None and self.maxTokens is None:
                max_tokens = min(max_tokens, max_output_tokens(model))
        if self.maxTokens is not None:
            max_tokens = min(self.maxTokens, max_output_tokens(model))
        if self.temperature is not None:
            temperature = self.temperature
        check_requested_llm(model, max_tokens)
        return model, temperature, max_tokens

    def search_limits(self, deep: bool) -> tuple[Optional[int], Optional[int]]:
        return (
            (self.deepSearches, self.deepSearchesPerStream)
            if deep
            else (self.searches, self.searchesPerStream)
        )


def assistant_search_defaults(deep: bool) -> tuple[int, int]:
    """Return the site's focused-question and per-stream budgets."""
    cfg = db_config.get_application_config().get("assistant", {})
    if deep:
        return cfg.get("deep_research", {}).get("max_queries", 10), 4
    return cfg.get("max_queries", 4), 2


def assistant_site_defaults() -> AssistantSettings:
    """Return the default research limits and prompts for Group Settings."""
    searches, per_stream = assistant_search_defaults(False)
    deep_searches, deep_per_stream = assistant_search_defaults(True)
    return AssistantSettings(
        searches=searches,
        searchesPerStream=per_stream,
        deepSearches=deep_searches,
        deepSearchesPerStream=deep_per_stream,
        deepResearchByDefault=False,
        planningInstructions=assistant_prompt_templates.get_template(
            "assistant_planning_instructions.j2"
        ).render(),
        answerInstructions=assistant_prompt_templates.get_template(
            "assistant_answer_instructions.j2"
        ).render(),
    )


def validate_assistant_settings(settings: dict) -> None:
    """Validate and normalize the Assistant entry before saving a group."""
    if ASSISTANT_SETTINGS_KEY not in settings:
        return
    try:
        assistant = AssistantSettings.model_validate(settings[ASSISTANT_SETTINGS_KEY])
    except ValidationError as exc:
        error = exc.errors(
            include_input=False, include_context=False, include_url=False
        )[0]
        field = ".".join(map(str, error["loc"])) or ASSISTANT_SETTINGS_KEY
        raise HTTPException(
            status_code=422, detail=f"Assistant {field}: {error['msg']}"
        ) from None
    if assistant.model is not None and assistant.model not in db_config.SUPPORTED_LLMS:
        raise HTTPException(
            status_code=422, detail="Choose an Assistant model this site offers."
        )
    if assistant.maxTokens is not None:
        maximum = max_output_tokens(assistant.model)
        if assistant.maxTokens > maximum:
            raise HTTPException(
                status_code=422,
                detail=f"Assistant maximum output tokens must be between 1 and {maximum}.",
            )
    settings[ASSISTANT_SETTINGS_KEY] = assistant.model_dump(exclude_none=True)


def assistant_settings_for_groups(groups: Sequence) -> AssistantSettings:
    """Take the first configured value for each Assistant setting by group name."""
    values: dict = {}
    prompt_slots = {
        "planningPrompt": "planningInstructions",
        "planningInstructions": "planningPrompt",
        "answerPrompt": "answerInstructions",
        "answerInstructions": "answerPrompt",
    }
    for group in groups:
        settings = (group.search_settings or {}).get(ASSISTANT_SETTINGS_KEY) or {}
        for key, value in settings.items():
            if prompt_slots.get(key) in values:
                continue
            if value is not None:
                values.setdefault(key, value)
    return AssistantSettings.model_validate(values)
