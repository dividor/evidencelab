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

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import func, select, update

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
    TestRun,
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


def _result_to_dict(r: Any) -> Dict[str, Any]:
    if hasattr(r, "model_dump"):
        return r.model_dump()
    if hasattr(r, "dict"):
        return r.dict()
    return r if isinstance(r, dict) else dict(r)


def _json_safe(obj: Any) -> Any:
    """Coerce an object graph to JSON-serialisable form (datetimes -> str, etc.)
    so it can be stored in a JSONB column."""
    return json.loads(json.dumps(obj, default=str))


# Per-result fields worth keeping for display/assertions; the rest (and the bulk
# of the payload) is dropped so stored ``actual_output`` stays small.
_RESULT_TEXT_LIMIT = 2000
_RESULT_KEEP = {
    "id",
    "chunk_id",
    "doc_id",
    "score",
    "title",
    "organization",
    "map_title",
    "map_organization",
    "country",
    "published_year",
    "document_type",
    "section_type",
    "url",
    "date",
    "published_date",
    "language",
}


def _compact_result(r: Any) -> Any:
    if not isinstance(r, dict):
        return r
    compact: Dict[str, Any] = {}
    for key, value in r.items():
        if key == "text" and isinstance(value, str):
            compact["text"] = value[:_RESULT_TEXT_LIMIT]
        elif key in _RESULT_KEEP:
            compact[key] = value
    return compact


def _storable_output(output: Any) -> Any:
    """Build a compact, JSON-safe copy of a case's raw output for persistence.

    Assertions have already run against the FULL output; this only shrinks what
    is stored (trimming per-result text and dropping bulky fields) and makes it
    JSON-serialisable.
    """
    if not isinstance(output, dict):
        return _json_safe(output)
    out = dict(output)
    for key in ("search_results", "results"):
        if isinstance(out.get(key), list):
            out[key] = [_compact_result(r) for r in out[key]]
    return _json_safe(out)


async def _run_search(
    case_input: Dict[str, Any], config: Dict[str, Any], db, pg, source: str
):
    """Run search through the EXACT same pipeline as the UI ``/search`` route
    (same retrieval, result building, field-boost/dedup post-processing), so an
    experiment reproduces what a user sees in the app.

    Parameters default to the ``/search`` endpoint's own defaults; the
    experiment ``config`` overrides them (e.g. ``embedding_model``, ``rerank``,
    ``field_boost_fields``, ``section_types``).
    """
    from ui.backend.routes.search import (
        _apply_post_retrieval_boosts,
        _fetch_and_build_results,
        _parse_section_types,
        _run_search_chunks,
    )

    params = {**(config or {}), **(case_input.get("params") or {})}
    query = case_input.get("query", "")
    limit = int(params.get("limit", 50))
    min_chunk_size = int(params.get("min_chunk_size", 0))
    raw = await _run_search_chunks(
        query,
        limit=limit,
        dense_weight=params.get("dense_weight"),
        db=db,
        filters=case_input.get("filters") or None,
        rerank=bool(params.get("rerank", False)),
        recency_boost=bool(params.get("recency_boost", False)),
        recency_weight=float(params.get("recency_weight", 0.15)),
        recency_scale_days=int(params.get("recency_scale_days", 365)),
        section_types=_parse_section_types(params.get("section_types")),
        keyword_boost_short_queries=bool(
            params.get("keyword_boost_short_queries", True)
        ),
        min_chunk_size=min_chunk_size,
        dense_model=params.get("embedding_model") or params.get("dense_model"),
        rerank_model=params.get("rerank_model"),
        max_rerank_candidates=int(params.get("max_rerank_candidates") or 0),
    )
    built = _fetch_and_build_results(pg, raw, source, limit, min_chunk_size)
    if not built:
        return {"query": query, "results": [], "count": 0}
    boosted = _apply_post_retrieval_boosts(
        built,
        query,
        bool(params.get("field_boost", True)),
        params.get("field_boost_fields"),
        bool(params.get("auto_min_score", False)),
        bool(params.get("deduplicate", True)),
        db,
        source,
    )
    results = [_result_to_dict(r) for r in boosted]
    return {"query": query, "results": results, "count": len(results)}


def _combo_summary_model(combo: Any) -> Optional[str]:
    sm = combo.get("summarization_model") if isinstance(combo, dict) else None
    if isinstance(sm, dict) and sm.get("model"):
        return sm["model"]
    return None


def _default_summary_model() -> Optional[str]:
    """Pick a sensible default summary model from the app's configured combos.

    Mirrors how the UI resolves a model: prefer the default ui_model_combo's
    summarization model, then any combo's, then the first supported LLM.
    """
    try:
        from pipeline.db.config import (
            SUPPORTED_LLMS,
            UI_MODEL_COMBOS,
            get_default_model_combo,
        )
    except Exception:
        logger.exception("Failed to import config for default summary model")
        return None
    default = _combo_summary_model(UI_MODEL_COMBOS.get(get_default_model_combo()))
    if default:
        return default
    for combo in UI_MODEL_COMBOS.values():
        model = _combo_summary_model(combo)
        if model:
            return model
    return next(iter(SUPPORTED_LLMS), None)


async def _run_summary(
    case_input: Dict[str, Any], config: Dict[str, Any], db, pg, source: str
):
    from ui.backend.services.llm_service import generate_ai_summary_with_usage

    search_out = await _run_search(case_input, config, db, pg, source)
    cfg = config or {}
    model_key = cfg.get("summary_model") or _default_summary_model()
    summary, usage = await generate_ai_summary_with_usage(
        query=case_input.get("query", ""),
        results=search_out["results"],
        max_results=int(cfg.get("max_results", 20)),
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


def _resolve_combo(name: Optional[str]) -> Dict[str, Optional[str]]:
    """Resolve a ui_model_combo (e.g. 'Google Vertex') to its embedding /
    summarization / reranker models — the same mapping the search UI uses."""
    if not name:
        return {}
    try:
        from pipeline.db.config import UI_MODEL_COMBOS
    except Exception:
        logger.exception("Failed to import UI_MODEL_COMBOS")
        return {}
    combo = UI_MODEL_COMBOS.get(name) or {}
    return {
        "embedding_model": combo.get("embedding_model"),
        "summary_model": _combo_summary_model(combo),
        "rerank_model": combo.get("reranker_model"),
    }


def effective_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge a chosen model combo into the run config so the harness uses the
    same embedding/summary/reranker models as the UI. Explicit config values
    take precedence over the combo's defaults."""
    cfg = dict(config or {})
    combo = _resolve_combo(cfg.get("model_combo"))
    for key in ("embedding_model", "summary_model", "rerank_model"):
        if not cfg.get(key) and combo.get(key):
            cfg[key] = combo[key]
    return cfg


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
# LLM judge (always on — an ``llm_judge`` assertion is enough to enable it)
# ---------------------------------------------------------------------------


def _parse_score(text: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", text or "")
    if not match:
        return 0.0
    return max(0.0, min(1.0, float(match.group(0))))


def _parse_judgement(text: str) -> Tuple[float, str]:
    """Parse a judge reply into ``(score in [0, 1], reason)``.

    Prefers a JSON object ``{"score": .., "reason": ..}``; falls back to the
    first number for the score and the raw text as the reason.
    """
    raw = text or ""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            score = max(0.0, min(1.0, float(data.get("score"))))
            return score, str(data.get("reason", "")).strip()
        except (ValueError, TypeError):
            pass
    return _parse_score(raw), raw.strip()


_JUDGE_SYSTEM_PROMPT = (
    "You are a meticulous, strict evaluator. You are given a rubric and an "
    "output to evaluate. Judge ONLY how well the output literally and precisely "
    "satisfies the rubric — do not invent extra criteria and do not reward the "
    "output for anything the rubric did not ask for. Respond with ONLY a JSON "
    'object {"score": <number 0.0-1.0>, "reason": "<one or two sentence '
    'justification that refers to the rubric>"}.'
)


async def _judge_call(prompt: str, model_key: Optional[str]) -> str:
    """Raw LLM completion for judging — deliberately NOT routed through the
    AI-summary templates (which would reframe the rubric as a search query)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from utils.llm_factory import get_llm

    llm = get_llm(model=model_key, temperature=0.0, max_tokens=300)
    response = await llm.ainvoke(
        [
            SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
    )
    return str(response.content)


def make_judge_factory(config: Dict[str, Any]) -> JudgeFactory:
    """Return an async judge factory that scores ``llm_judge`` assertions.

    Always enabled: adding an ``llm_judge`` assertion is sufficient (no separate
    config flag). Each distinct rubric is judged once per case via a raw LLM
    call, asking for both a score and a short reason.
    """
    cfg = config or {}
    model_key = (
        cfg.get("judge_model") or cfg.get("summary_model") or _default_summary_model()
    )

    async def factory(output, expectations):
        text = str(output.get("summary", "") or "")
        verdicts: Dict[str, Tuple[float, str, str]] = {}
        for assertion in expectations:
            if assertion.get("type") != "llm_judge":
                continue
            rubric = str(assertion.get("rubric", ""))
            if rubric in verdicts:
                continue
            user_prompt = (
                f"Rubric:\n{rubric}\n\nOutput to evaluate:\n{text}\n\n"
                "Return ONLY the JSON object."
            )
            full_prompt = f"SYSTEM:\n{_JUDGE_SYSTEM_PROMPT}\n\nUSER:\n{user_prompt}"
            logger.info("[LLM judge] model=%s rubric=%r", model_key, rubric[:300])
            judged = await _judge_call(user_prompt, model_key)
            logger.info("[LLM judge] response=%r", judged[:400])
            score, reason = _parse_judgement(judged)
            verdicts[rubric] = (score, reason, full_prompt)
        return lambda _text, rubric: verdicts.get(str(rubric), (0.0, "", ""))

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


def _resolve_case_plan(
    case_expectations: Dict[str, Any], case_id: str
) -> Tuple[bool, List[Dict[str, Any]]]:
    """From the assertion matrix, return ``(is_active, active_assertions)``.

    Matrix shape::

        {"columns": [assertion, ...],
         "cases": {case_id: {"active": bool, "cols": [bool, ...]}}}

    Inactive or unknown cases return ``(False, [])`` and are skipped by the
    runner. Only assertion columns whose aligned ``cols`` flag is true (and that
    reference a real column) are returned.
    """
    matrix = case_expectations or {}
    columns = matrix.get("columns") or []
    state = (matrix.get("cases") or {}).get(case_id)
    if not isinstance(state, dict) or not state.get("active", False):
        return False, []
    cols = state.get("cols") or []
    assertions = [
        columns[i]
        for i, enabled in enumerate(cols)
        if enabled and i < len(columns) and isinstance(columns[i], dict)
    ]
    return True, assertions


async def _next_run_number(session, experiment_id) -> int:
    result = await session.execute(
        select(func.max(TestRun.run_number)).where(
            TestRun.experiment_id == experiment_id
        )
    )
    return int(result.scalar() or 0) + 1


def _mirror_run_to_experiment(experiment: TestExperiment, run: TestRun) -> None:
    """Reflect a run's outcome onto the experiment for the list/summary view."""
    experiment.status = run.status
    experiment.summary_stats = dict(run.summary_stats) if run.summary_stats else None
    experiment.started_at = run.started_at
    experiment.finished_at = run.finished_at


async def _fail_run(
    session, experiment: TestExperiment, run: TestRun, message: str
) -> None:
    run.status = EXPERIMENT_FAILED
    run.finished_at = _utcnow()
    run.summary_stats = {"error": message[:500]}
    _mirror_run_to_experiment(experiment, run)
    await session.commit()


async def _mark_failed(session, experiment: TestExperiment, message: str) -> None:
    """Catastrophic-failure path: fail the experiment and any running run."""
    # The triggering error may have left the session in a failed transaction;
    # roll back so these status writes can commit.
    await session.rollback()
    experiment = await session.get(TestExperiment, experiment.id) or experiment
    await session.execute(
        update(TestRun)
        .where(
            TestRun.experiment_id == experiment.id,
            TestRun.status == EXPERIMENT_RUNNING,
        )
        .values(
            status=EXPERIMENT_FAILED,
            finished_at=_utcnow(),
            summary_stats={"error": message[:500]},
        )
    )
    experiment.status = EXPERIMENT_FAILED
    experiment.finished_at = _utcnow()
    experiment.summary_stats = {"error": message[:500]}
    await session.commit()


async def _execute(session, experiment: TestExperiment) -> None:
    dataset = await session.get(TestDataset, experiment.dataset_id)
    started = time.time()
    # Each execution is a new run; prior runs and their results are preserved.
    run = TestRun(
        experiment_id=experiment.id,
        run_number=await _next_run_number(session, experiment.id),
        status=EXPERIMENT_RUNNING,
        started_at=_utcnow(),
        created_by_user_id=experiment.created_by_user_id,
    )
    session.add(run)
    experiment.status = EXPERIMENT_RUNNING
    experiment.started_at = run.started_at
    experiment.finished_at = None
    await session.commit()
    await session.refresh(run)

    if dataset is None:
        await _fail_run(session, experiment, run, "Dataset not found")
        return
    # Resolve the chosen model combo into concrete embedding/summary/reranker
    # models so the run uses the same configuration as the search UI.
    config = effective_config(experiment.config)
    try:
        runner = build_case_runner(dataset.capability, config, dataset.data_source)
    except Exception as exc:
        logger.exception("Failed to build case runner")
        await _fail_run(session, experiment, run, str(exc))
        return
    judge_factory = make_judge_factory(config)
    matrix = experiment.case_expectations or {}
    case_results: List[Dict[str, Any]] = []
    for case in await _load_cases(session, dataset.id):
        active, assertions = _resolve_case_plan(matrix, str(case.id))
        if not active:
            continue
        outcome = await evaluate_case(case.input, assertions, runner, judge_factory)
        case_results.append(outcome)
        # Persist a compact, JSON-safe copy (full output can carry datetimes and
        # be megabytes large); assertions already ran against the full output.
        stored = dict(outcome)
        stored["actual_output"] = _storable_output(outcome.get("actual_output"))
        stored["assertion_results"] = _json_safe(outcome.get("assertion_results"))
        session.add(
            TestResult(
                experiment_id=experiment.id,
                run_id=run.id,
                test_case_id=case.id,
                **stored,
            )
        )
    run.summary_stats = compute_summary_stats(
        case_results, int((time.time() - started) * 1000)
    )
    run.status = EXPERIMENT_COMPLETED
    run.finished_at = _utcnow()
    _mirror_run_to_experiment(experiment, run)
    await session.commit()


async def run_experiment(experiment_id, session_factory=None) -> None:
    """Background entrypoint: load the experiment and execute one run of it."""
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
