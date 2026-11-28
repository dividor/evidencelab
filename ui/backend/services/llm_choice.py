"""Which model each AI job uses.

An administrator can choose, per group, the model that writes the search AI
summary, the model that writes Briefs, and the model that judges evaluations
(Group Settings > LLMs). The choices are stored in the group's
``search_settings`` under :data:`JOB_SETTING`'s keys. A group's choice
overrides config.json, including the model combo a user picked; without one, a
job uses the model the request names (its model combo's) or config.json's
default for it.

The API decides, not the browser, so usage records and the activity log hold
the model that actually ran. Named groups take precedence over the default
group, with group name breaking ties.
"""

import logging
from typing import Any, Dict, Optional, Sequence

from fastapi import HTTPException

from pipeline.db import config as db_config

logger = logging.getLogger(__name__)

SUMMARY = "summary"
BRIEF = "brief"
JUDGE = "judge"
CITATION_CHECK = "citation_check"

# The search_settings key each job's group choice is stored under.
JOB_SETTING: Dict[str, str] = {
    SUMMARY: "summaryModel",
    BRIEF: "briefModel",
    JUDGE: "judgeModel",
    CITATION_CHECK: "citationCheckModel",
}

# What each job is called in messages.
JOB_LABEL: Dict[str, str] = {
    SUMMARY: "the search AI summary",
    BRIEF: "Briefs",
    JUDGE: "evaluation judging",
    CITATION_CHECK: "automatic citation checking",
}


def validate_group_model_choices(settings: Optional[Dict[str, Any]]) -> None:
    """Refuse a group's settings that choose a model config.json doesn't list.

    Raises HTTPException(422) naming the setting, the value and the models
    that can be chosen.
    """
    if not settings:
        return
    for key in JOB_SETTING.values():
        value = settings.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or value not in db_config.SUPPORTED_LLMS:
            listed = ", ".join(db_config.SUPPORTED_LLMS) or "none"
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{key} must be one of the models in config.json's "
                    f"supported_llms ({listed}); got {value!r}"
                ),
            )


def group_choice(groups: Sequence[Any], job: str) -> Optional[str]:
    """Choose from named groups first and the default group last.

    Within each group, citation checking uses the group's evaluation judge
    when the group has no explicit citation checker.
    """
    jobs = (CITATION_CHECK, JUDGE) if job == CITATION_CHECK else (job,)
    for group in sorted(groups, key=lambda item: (item.is_default, item.name)):
        settings = group.search_settings or {}
        for candidate in jobs:
            value = settings.get(JOB_SETTING[candidate])
            if value:
                return _validate_group_choice(group.name, candidate, value)
    return None


def _validate_group_choice(group_name: str, job: str, value: str) -> str:
    if value not in db_config.SUPPORTED_LLMS:
        logger.error(
            "Group %r chooses %r for %s, which config.json does not list",
            group_name,
            value,
            job,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"The group '{group_name}' uses the model '{value}' for "
                f"{JOB_LABEL[job]}, but this site no longer offers it. An "
                "administrator must choose another in Group Settings > LLMs."
            ),
        )
    return value


async def user_group_choice(session: Any, user: Any, job: str) -> Optional[str]:
    """The model the user's groups choose for ``job``; None when they don't,
    or when there is no signed-in user."""
    if session is None or user is None or getattr(user, "id", None) is None:
        return None
    from ui.backend.services.group_settings import user_groups

    return group_choice(await user_groups(session, user.id), job)


def _stage_model(combo: Dict[str, Any], stage: str) -> Optional[str]:
    settings = combo.get(stage)
    model = settings.get("model") if isinstance(settings, dict) else settings
    return str(model) if model else None


def combo_default(job: str, combo: Optional[Dict[str, Any]]) -> Optional[str]:
    """config.json's model for ``job`` in a model combo.

    Search summary: ``summarization_model``. Brief: ``assistant_model``, else
    ``summarization_model``. Judge: ``judge_model``, else
    ``summarization_model`` (the model under test then grades itself, which
    is why ``judge_model`` should be set).
    """
    combo = combo or {}
    summary = _stage_model(combo, "summarization_model")
    if job == SUMMARY:
        return summary
    if job == BRIEF:
        return _stage_model(combo, "assistant_model") or summary
    if job in (JUDGE, CITATION_CHECK):
        return _stage_model(combo, "judge_model") or summary
    raise ValueError(f"Unknown AI job {job!r}")


def default_combo() -> Dict[str, Any]:
    """The model combo a visitor starts on."""
    return db_config.UI_MODEL_COMBOS.get(db_config.get_default_model_combo()) or {}


def run_combo(name: Optional[str]) -> Dict[str, Any]:
    if name is None:
        return default_combo()
    if name not in db_config.UI_MODEL_COMBOS:
        raise HTTPException(status_code=422, detail="Unknown model combo.")
    return db_config.UI_MODEL_COMBOS[name]


def config_defaults() -> Dict[str, Optional[str]]:
    """config.json's model for each job, in the default model combo."""
    combo = default_combo()
    return {job: combo_default(job, combo) for job in JOB_SETTING}
