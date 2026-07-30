"""Admin TOC validator — superuser-only routes.

Runs the section-inclusion check over selected documents and persists the result
on each document. Checks the *current* classification only (no re-tagging); the
work is pure string parsing so it runs synchronously in a threadpool. Every
endpoint is gated with ``Depends(current_superuser)`` and rate-limited. Errors
are returned generically per SECURITY.md; full detail is logged server-side.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ui.backend.auth.models import User
from ui.backend.auth.users import current_superuser
from ui.backend.services import toc_validator as service
from ui.backend.utils.app_limits import get_rate_limits, limiter

logger = logging.getLogger(__name__)

router = APIRouter()
_RL_SEARCH, _RL_DEFAULT, _RL_AI = get_rate_limits()

# Cap how many documents one request may validate (defence-in-depth alongside
# the request-body-size middleware).
MAX_DOC_IDS = 2000


class TocValidatorRunRequest(BaseModel):
    data_source: Optional[str] = None
    doc_ids: List[str] = Field(..., min_length=1, max_length=MAX_DOC_IDS)


class TocValidatorRunResponse(BaseModel):
    results: List[Dict[str, Any]]


class TocValidatorResultsResponse(BaseModel):
    results: Dict[str, Dict[str, Any]]


def _get_pg(data_source: Optional[str]):
    """Resolve a PostgresClient for the data source, validating it first."""
    from ui.backend.utils.app_state import get_pg_for_source

    try:
        return get_pg_for_source(data_source)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid data_source: {data_source}"
        )
    except Exception:
        logger.exception("data_source validation failed")
        raise HTTPException(status_code=400, detail="Invalid data_source")


@router.post("/run", response_model=TocValidatorRunResponse, tags=["toc-validator"])
@limiter.limit(_RL_DEFAULT)
async def run_validation(
    request: Request,
    body: TocValidatorRunRequest,
    admin: User = Depends(current_superuser),
) -> TocValidatorRunResponse:
    """Validate the given documents and persist each result."""
    pg = _get_pg(body.data_source)
    try:
        results = await run_in_threadpool(
            service.run_validation, pg, body.doc_ids, admin.email
        )
    except Exception:
        logger.exception("TOC validation run failed")
        raise HTTPException(status_code=500, detail="TOC validation failed")
    return TocValidatorRunResponse(results=results)


@router.get(
    "/results", response_model=TocValidatorResultsResponse, tags=["toc-validator"]
)
@limiter.limit(_RL_DEFAULT)
async def get_results(
    request: Request,
    data_source: Optional[str] = Query(None),
    admin: User = Depends(current_superuser),
) -> TocValidatorResultsResponse:
    """Return previously-stored validation results for a data source."""
    pg = _get_pg(data_source)
    try:
        results = await run_in_threadpool(service.get_stored_results, pg, None)
    except Exception:
        logger.exception("Fetching TOC validation results failed")
        raise HTTPException(status_code=500, detail="Could not load results")
    return TocValidatorResultsResponse(results=results)
