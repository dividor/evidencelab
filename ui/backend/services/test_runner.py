"""Run engine for the admin evaluation harness.

Invokes the REAL search / AI-summary code paths for each test case, captures
the full raw output + latency, evaluates the case's assertions, and persists a
``test_results`` row. A failing/erroring case never aborts the run (it is
recorded as ``error`` with a message). On completion the engine aggregates and
persists ``summary_stats``.

The pure-ish, unit-testable pieces (``evaluate_case``, ``compute_summary_stats``)
take an injected ``runner``/``judge_fn_factory`` so they can be exercised with
fakes; ``run_experiment`` does the live wiring + DB orchestration. Experiments
run as a background task (the route returns immediately; the UI polls status).
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select

from ui.backend.auth.db import async_session_factory
from ui.backend.auth.testing_models import (
    CAPABILITY_AI_SUMMARY,
    CAPABILITY_SEARCH,
    EXPERIMENT_COMPLETED,
    EXPERIMENT_FAILED,
    EXPERIMENT_RUNNING,
    RESULT_ERROR,
    RESULT_FAIL,
    RESULT_PASS,
    TestCase,
    TestDataset,
    TestExperiment,
    TestResult,
)
from ui.backend.services.evaluation_metrics import compute_summary_stats
from ui.backend.services.test_evaluators import evaluate_assertions

logger = logging.getLogger(__name__)

CaseRunner = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
JudgeFactory = Callable[
    [Dict[str, Any], List[Dict[str, Any]]], Awaitable[Callable[[str, str], float]]
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Live capability invocation
# ---------------------------------------------------------------------------


def _result_from_point(point: Any, chunk: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(getattr(point, "payload", None) or {})
    cid = str(point.id)
    enriched = {
        "id": cid,
        "chunk_id": cid,
        "score": float(getattr(point, "score", 0.0) or 0.0),
        "doc_id": payload.get("doc_id") or chunk.get("doc_id"),
        "text": chunk.get("text", ""),
        "title": payload.get("map_title") or chunk.get("map_title"),
        "organization": payload.get("map_organization")
        or chunk.get("map_organization"),
    }
    enriched.update(payload)
    return enriched


def _enrich_points(points: List[Any], pg: Any) -> List[Dict[str, Any]]:
    chunk_ids = [str(p.id) for p in points]
    chunk_data: Dict[str, Dict[str, Any]] = {}
    if chunk_ids and pg is not None:
        try:
            chunk_data = pg.fetch_chunks(chunk_ids)
        except Exception:
            logger.exception("fetch_chunks failed during eval enrichment")
    return [_result_from_point(p, chunk_data.get(str(p.id), {})) for p in points]


async def _run_search(
    case_input: Dict[str, Any], config: Dict[str, Any], db, pg, source: str
):
    from ui.backend.services.search import search_chunks

    params = {**(config or {}), **(case_input.get("params") or {})}
    points = await run_in_threadpool(
        search_chunks,
        case_input.get("query", ""),
        limit=int(params.get("limit", 10)),
        db=db,
        data_source=source,
        filters=case_input.get("filters") or None,
        rerank=bool(params.get("rerank", False)),
        dense_model=params.get("dense_model"),
    )
    results = _enrich_points(points, pg)
    return {
        "query": case_input.get("query", ""),
        "results": results,
        "count": len(results),
    }


def _default_summary_model() -> Optional[str]:
    """Pick a sensible default summary model from config when none is set."""
    try:
        from pipeline.db.config import get_application_config

        config = get_application_config()
    except Exception:
        logger.exception("Failed to load config for default summary model")
        return None
    for combo in (config.get("ui_model_combos") or {}).values():
        sm = combo.get("summarization_model") if isinstance(combo, dict) else None
        if isinstance(sm, dict) and sm.get("model"):
            return sm["model"]
    return next(iter(config.get("supported_llms") or {}), None)


async def _run_summary(
    case_input: Dict[str, Any], config: Dict[str, Any], db, pg, source: str
):
    from ui.backend.services.llm_service import generate_ai_summary_with_usage

    search_out = await _run_search(case_input, config, db, pg, source)
    cfg = config or {}
    model_key = cfg.get("summary_model") or cfg.get("model") or _default_summary_model()
    summary, usage = await generate_ai_summary_with_usage(
        query=case_input.get("query", ""),
        results=search_out["results"],
        model_key=model_key,
        temperature=cfg.get("temperature"),
        max_tokens=cfg.get("max_tokens"),
    )
    return {
        "query": case_input.get("query", ""),
        "summary": summary,
        "usage": usage,
        "search_results": search_out["results"],
    }


def build_case_runner(
    capability: str, config: Dict[str, Any], data_source: str
) -> CaseRunner:
    """Build a live per-case runner. Validates ``data_source`` (raises ValueError)."""
    from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source

    db = get_db_for_source(data_source)
    pg = get_pg_for_source(data_source)
    if capability == CAPABILITY_SEARCH:
        return lambda case_input: _run_search(case_input, config, db, pg, data_source)
    if capability == CAPABILITY_AI_SUMMARY:
        return lambda case_input: _run_summary(case_input, config, db, pg, data_source)
    raise ValueError(f"Unknown capability: {capability!r}")


# ---------------------------------------------------------------------------
# LLM judge (optional, config-gated)
# ---------------------------------------------------------------------------


def _parse_score(text: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", text or "")
    if not match:
        return 0.0
    return max(0.0, min(1.0, float(match.group(0))))


def make_judge_factory(config: Dict[str, Any]) -> Optional[JudgeFactory]:
    """Return an async judge factory if ``enable_llm_judge`` is set, else None."""
    if not (config or {}).get("enable_llm_judge"):
        return None
    model_key = (
        config.get("judge_model") or config.get("summary_model") or config.get("model")
    )

    async def factory(output, expectations):
        from ui.backend.services.llm_service import generate_ai_summary_with_usage

        text = str(output.get("summary", "") or "")
        scores: Dict[str, float] = {}
        for assertion in expectations:
            if assertion.get("type") != "llm_judge":
                continue
            rubric = str(assertion.get("rubric", ""))
            if rubric in scores:
                continue
            prompt = (
                f"Rubric: {rubric}\n\nOutput to evaluate:\n{text}\n\n"
                "Score how well the output satisfies the rubric from 0.0 to 1.0. "
                "Respond with ONLY the number."
            )
            judged, _usage = await generate_ai_summary_with_usage(
                query=prompt, results=[], model_key=model_key, temperature=0.0
            )
            scores[rubric] = _parse_score(judged)
        return lambda _text, rubric: scores.get(str(rubric), 0.0)

    return factory


# ---------------------------------------------------------------------------
# Per-case evaluation (testable with an injected runner/judge factory)
# ---------------------------------------------------------------------------


async def evaluate_case(
    case_input: Dict[str, Any],
    expectations: List[Dict[str, Any]],
    runner: CaseRunner,
    judge_factory: Optional[JudgeFactory] = None,
) -> Dict[str, Any]:
    """Run one case and evaluate its assertions. Errors are isolated, not raised."""
    started = time.time()
    try:
        output = await runner(case_input)
    except Exception as exc:
        logger.exception("Evaluation case errored")
        return {
            "status": RESULT_ERROR,
            "score": None,
            "actual_output": None,
            "assertion_results": None,
            "latency_ms": int((time.time() - started) * 1000),
            "error_message": str(exc)[:500],
        }
    latency_ms = int((time.time() - started) * 1000)
    judge_fn = await judge_factory(output, expectations) if judge_factory else None
    assertion_results, passed, score = evaluate_assertions(
        expectations, output, judge_fn=judge_fn
    )
    return {
        "status": RESULT_PASS if passed else RESULT_FAIL,
        "score": score,
        "actual_output": output,
        "assertion_results": assertion_results,
        "latency_ms": latency_ms,
        "error_message": None,
    }


# ---------------------------------------------------------------------------
# Experiment orchestration (DB + live wiring)
# ---------------------------------------------------------------------------


async def _load_cases(session, dataset_id) -> List[TestCase]:
    result = await session.execute(
        select(TestCase).where(TestCase.dataset_id == dataset_id)
    )
    return list(result.scalars().all())


async def _mark_failed(session, experiment: TestExperiment, message: str) -> None:
    experiment.status = EXPERIMENT_FAILED
    experiment.finished_at = _utcnow()
    experiment.summary_stats = {"error": message[:500]}
    await session.commit()


async def _execute(session, experiment: TestExperiment) -> None:
    dataset = await session.get(TestDataset, experiment.dataset_id)
    if dataset is None:
        await _mark_failed(session, experiment, "Dataset not found")
        return
    started = time.time()
    # Clear any results from a previous run so re-runs reflect the latest pass.
    await session.execute(
        delete(TestResult).where(TestResult.experiment_id == experiment.id)
    )
    experiment.status = EXPERIMENT_RUNNING
    experiment.started_at = _utcnow()
    experiment.finished_at = None
    await session.commit()
    config = experiment.config or {}
    try:
        runner = build_case_runner(dataset.capability, config, dataset.data_source)
    except Exception as exc:
        logger.exception("Failed to build case runner")
        await _mark_failed(session, experiment, str(exc))
        return
    judge_factory = make_judge_factory(config)
    case_expectations = experiment.case_expectations or {}
    case_results: List[Dict[str, Any]] = []
    for case in await _load_cases(session, dataset.id):
        expectations = case_expectations.get(str(case.id), [])
        outcome = await evaluate_case(case.input, expectations, runner, judge_factory)
        session.add(
            TestResult(experiment_id=experiment.id, test_case_id=case.id, **outcome)
        )
        case_results.append(outcome)
    experiment.summary_stats = compute_summary_stats(
        case_results, int((time.time() - started) * 1000)
    )
    experiment.status = EXPERIMENT_COMPLETED
    experiment.finished_at = _utcnow()
    await session.commit()


async def run_experiment(experiment_id, session_factory=None) -> None:
    """Background entrypoint: load the experiment and execute it end-to-end."""
    factory = session_factory or async_session_factory
    async with factory() as session:
        experiment = await session.get(TestExperiment, experiment_id)
        if experiment is None:
            logger.error("run_experiment: experiment %s not found", experiment_id)
            return
        try:
            await _execute(session, experiment)
        except Exception:
            logger.exception("Experiment %s failed unexpectedly", experiment_id)
            await _mark_failed(session, experiment, "Experiment failed")
