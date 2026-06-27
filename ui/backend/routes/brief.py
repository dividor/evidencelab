"""Brief tab routes — research-brief outline generation.

The Brief tab assembles an evidence brief from section headings, then runs the
existing deep-research assistant (``/assistant/chat/stream``) per section. The
only net-new capability needed server-side is turning a user's question into a
starter outline, which this thin endpoint provides via the shared LLM client.

Per-section research and synthesis reuse the assistant route; no new search or
synthesis code lives here. Errors are returned generically per SECURITY.md;
full detail is logged server-side only.
"""

import logging
import sys
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from ui.backend.schemas import BriefHeading, BriefOutlineRequest, BriefOutlineResponse
from ui.backend.services import llm_service as llm_service_module
from ui.backend.utils.app_limits import get_rate_limits, limiter

logger = logging.getLogger(__name__)

router = APIRouter()
_RL_SEARCH, _RL_DEFAULT, RATE_LIMIT_AI = get_rate_limits()

# Guardrail: a brief question is a short prompt, not a document.
_MAX_QUESTION_CHARS = 2000


def _validate_data_source(source: str) -> None:
    """Validate against the config.json whitelist (canonical app_state path)."""
    from ui.backend.utils.app_state import get_db_for_source

    try:
        get_db_for_source(source)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid data_source: {source}")
    except Exception:
        logger.exception("data_source validation failed")
        raise HTTPException(status_code=400, detail="Invalid data_source")


def _get_llm_service():
    """Resolve the LLM service module from runtime or fallback imports."""
    return (
        sys.modules.get("llm_service")
        or sys.modules.get("ui.backend.services.llm_service")
        or llm_service_module
    )


def _resolve_configured_model(data_source: str) -> Optional[str]:
    """Resolve the configured chat / deep-research LLM from config.json.

    Mirrors the frontend's combo resolution (``assistant_model`` then
    ``summarization_model``) over the model combos available for this data
    source, so the Brief tab uses the same model as the rest of the system
    rather than a hard-coded default — and works regardless of frontend timing.
    """
    try:
        from ui.backend.routes.config import get_config_model_combos

        combos = get_config_model_combos(data_source)
        for combo in combos.values():
            model_cfg = combo.get("assistant_model") or combo.get("summarization_model")
            if isinstance(model_cfg, dict) and model_cfg.get("model"):
                return str(model_cfg["model"])
    except Exception:
        logger.exception("Could not resolve configured model from config.json")
    return None


@router.post("/brief/outline", response_model=BriefOutlineResponse)
@limiter.limit(RATE_LIMIT_AI)
async def generate_outline(
    request: Request, body: BriefOutlineRequest
) -> BriefOutlineResponse:
    """Generate a research-brief outline (title + section headings) from a question."""
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if len(question) > _MAX_QUESTION_CHARS:
        raise HTTPException(status_code=400, detail="question is too long")
    _validate_data_source(body.data_source)

    # Use the model the frontend sent (the selected combo), falling back to the
    # configured chat/deep-research model from config.json — never a hard-coded
    # default — so the outline works even before the UI's combo fetch resolves.
    model_key = (body.model or "").strip() or _resolve_configured_model(
        body.data_source
    )
    if not model_key:
        raise HTTPException(
            status_code=503, detail="No chat/deep-research model is configured"
        )

    sources = [s.model_dump() for s in body.sources] if body.sources else None

    try:
        llm_service = _get_llm_service()
        title, headings = await llm_service.generate_brief_outline(
            question=question, model_key=model_key, sources=sources
        )
        return BriefOutlineResponse(
            title=title,
            headings=[BriefHeading(**h) for h in headings],
        )
    except Exception:
        logger.error("Brief outline generation failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate outline")
