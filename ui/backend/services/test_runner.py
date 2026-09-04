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
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import func, select, update

from ui.backend.auth.db import async_session_factory
from ui.backend.auth.testing_models import (
    CAPABILITY_AI_SUMMARY,
    CAPABILITY_SEARCH,
    EXPERIMENT_COMPLETED,
    EXPERIMENT_FAILED,
    EXPERIMENT_PENDING,
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
from ui.backend.services.citations import render_reference_lines
from ui.backend.services.evaluation_metrics import compute_summary_stats
from ui.backend.services.test_evaluators import evaluate_assertions
from ui.backend.utils.filter_helpers import resolve_doc_level_filters

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
    """Run search through the same retrieval pipeline as the UI ``/search`` route
    (same retrieval, result building, field-boost/dedup post-processing), so an
    experiment reproduces what a user sees in the app.

    Document-level filters (``doc_titles``, ``region``, ``language`` and the
    data source's ``src_*`` fields) are resolved to ``doc_id`` filters here (via
    :func:`resolve_doc_level_filters`) because the harness calls the chunk
    search directly and so bypasses the route handler's own resolvers.

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
    filters = case_input.get("filters") or None
    if filters:
        filters = resolve_doc_level_filters(filters, pg, source)
    raw = await _run_search_chunks(
        query,
        limit=limit,
        dense_weight=params.get("dense_weight"),
        db=db,
        filters=filters,
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
    raw_summary, usage = await generate_ai_summary_with_usage(
        query=case_input.get("query", ""),
        results=search_out["results"],
        max_results=int(cfg.get("max_results", 20)),
        model_key=model_key,
        temperature=cfg.get("temperature"),
        max_tokens=cfg.get("max_tokens"),
        system_prompt_override=cfg.get("summary_prompt"),
    )
    # Resolve the inline [N] citation markers to their documents, exactly as the
    # UI does, so the evaluated summary carries titles/links and assertions can
    # test references. The full summary (raw text + References) is what is judged.
    references = _build_references(raw_summary, search_out["results"])
    full_summary = raw_summary + _references_text(references)
    return {
        "query": case_input.get("query", ""),
        "summary": full_summary,
        "raw_summary": raw_summary,
        "references": references,
        "usage": usage,
        "search_results": search_out["results"],
    }


# Inline citation markers in the summary, e.g. "[3]" or "[3, 4]".
_CITATION_RE = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")


def _build_references(
    summary: str, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Map cited [N] markers to the Nth search result (the UI's citation model)."""
    cited: List[int] = []
    seen = set()
    for match in _CITATION_RE.finditer(summary or ""):
        for part in match.group(1).split(","):
            try:
                num = int(part.strip())
            except ValueError:
                continue
            if num not in seen:
                seen.add(num)
                cited.append(num)
    references: List[Dict[str, Any]] = []
    for num in sorted(cited):
        idx = num - 1
        if not (0 <= idx < len(results)):
            continue
        r = results[idx] if isinstance(results[idx], dict) else {}
        references.append(
            {
                "number": num,
                "title": r.get("title") or r.get("map_title"),
                "organization": r.get("organization") or r.get("map_organization"),
                "year": r.get("year") or r.get("published_year"),
                "country": r.get("country"),
                "doc_id": r.get("doc_id"),
                "url": r.get("url") or r.get("link"),
                # Page of the cited chunk, carried through so the rendered
                # References can show ``p.<page>`` exactly as the search UI does.
                "page_num": r.get("page_num"),
            }
        )
    return references


def _references_text(references: List[Dict[str, Any]]) -> str:
    """Render references as an appended section, grouped by document with each
    citation's page number — the same shape the search UI shows (see
    :mod:`ui.backend.services.citations`)."""
    lines = render_reference_lines(references)
    if not lines:
        return ""
    return "\n".join(["", "", "## References", *lines])


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
    sm = combo.get("summarization_model")
    sm = sm if isinstance(sm, dict) else {}
    return {
        "embedding_model": combo.get("embedding_model"),
        "summary_model": _combo_summary_model(combo),
        "rerank_model": combo.get("reranker_model"),
        # Use the combo's summary token budget + temperature so the summary is
        # generated in full (not cut off by a small default max_tokens).
        "max_tokens": sm.get("max_tokens"),
        "temperature": sm.get("temperature"),
    }


# Group search_settings (camelCase) -> run-config keys consumed by _run_search.
# Mirrors the frontend useGroupDefaults param mapping so "run as group" matches
# what that group's members see in the search UI.
_GROUP_SETTING_MAP = {
    "denseWeight": "dense_weight",
    "rerank": "rerank",
    "recencyBoost": "recency_boost",
    "recencyWeight": "recency_weight",
    "recencyScaleDays": "recency_scale_days",
    "keywordBoostShortQueries": "keyword_boost_short_queries",
    "minChunkSize": "min_chunk_size",
    "autoMinScore": "auto_min_score",
    "deduplicate": "deduplicate",
    "fieldBoost": "field_boost",
}


def _group_settings_to_config(settings: Any) -> Dict[str, Any]:
    """Translate a group's ``search_settings`` blob into run-config keys."""
    out: Dict[str, Any] = {}
    if not isinstance(settings, dict):
        return out
    for camel, snake in _GROUP_SETTING_MAP.items():
        if settings.get(camel) is not None:
            out[snake] = settings[camel]
    sections = settings.get("sectionTypes")
    if isinstance(sections, list) and sections:
        out["section_types"] = ",".join(str(s) for s in sections)
    elif isinstance(sections, str) and sections:
        out["section_types"] = sections
    boost = settings.get("fieldBoostFields")
    if isinstance(boost, dict) and boost:
        out["field_boost_fields"] = ",".join(f"{k}:{v}" for k, v in boost.items())
    elif isinstance(boost, str) and boost:
        out["field_boost_fields"] = boost
    return out


async def _apply_group(session, config: Dict[str, Any]) -> Dict[str, Any]:
    """If ``group_id`` is set, overlay that group's search settings + summary
    prompt so the run reproduces that group's configured behaviour."""
    group_id = config.get("group_id")
    if not group_id:
        return config
    try:
        from ui.backend.auth.models import UserGroup

        group = await session.get(UserGroup, uuid.UUID(str(group_id)))
    except Exception:
        logger.exception("Failed to resolve group %s", group_id)
        return config
    if group is None:
        return config
    config.update(_group_settings_to_config(group.search_settings))
    if group.summary_prompt:
        config["summary_prompt"] = group.summary_prompt
    return config


def effective_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge a chosen model combo into the run config so the harness uses the
    same embedding/summary/reranker models as the UI. Explicit config values
    take precedence over the combo's defaults."""
    cfg = dict(config or {})
    combo = _resolve_combo(cfg.get("model_combo"))
    for key in (
        "embedding_model",
        "summary_model",
        "rerank_model",
        "max_tokens",
        "temperature",
    ):
        if cfg.get(key) is None and combo.get(key) is not None:
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
    "You are a meticulous, strict evaluator. The prompt has four clearly "
    "delimited sections: the RUBRIC, the AI SUMMARY, the REFERENCES, and the "
    "SEARCH RESULTS.\n"
    "- You judge ONLY the AI SUMMARY against the RUBRIC, literally and precisely "
    "— do not invent extra criteria.\n"
    "- The REFERENCES (documents resolved from the summary's [N] citations) and "
    "the SEARCH RESULTS (source passages the summary was generated from) are "
    "CONTEXT ONLY — they are NOT part of the summary. Use them only to check "
    "grounding (whether the summary's claims/citations are supported).\n"
    'Respond with ONLY a JSON object {"score": <number 0.0-1.0>, '
    '"reason": "<one or two sentence justification that refers to the rubric>"}.'
)

# How much of each source to include as grounding context for the judge.
_JUDGE_CONTEXT_MAX_RESULTS = 20
_JUDGE_CONTEXT_TEXT_LIMIT = 1200


def _format_judge_references(references: List[Dict[str, Any]]) -> str:
    """Grouped, page-numbered citation list for the judge (no markdown header) —
    the same rendering the search UI and the stored summary use (see
    :mod:`ui.backend.services.citations`)."""
    lines = render_reference_lines(references)
    if not lines:
        return "(no citations resolved in the summary)"
    return "\n".join(lines)


def _format_judge_context(output: Dict[str, Any]) -> str:
    """Render the search results the summary was built from, numbered to match
    the inline [N] citations, so the judge can assess grounding."""
    results = output.get("search_results") or output.get("results") or []
    blocks = []
    for i, r in enumerate(results[:_JUDGE_CONTEXT_MAX_RESULTS], start=1):
        if not isinstance(r, dict):
            continue
        title = r.get("title") or r.get("map_title") or r.get("doc_id") or "Untitled"
        org = r.get("organization") or r.get("map_organization") or ""
        meta = f" ({org})" if org else ""
        text = str(r.get("text") or "")[:_JUDGE_CONTEXT_TEXT_LIMIT]
        blocks.append(f"[{i}] {title}{meta}\n{text}".strip())
    return "\n\n".join(blocks) if blocks else "(no search results)"


async def _judge_call(
    prompt: str, model_key: Optional[str]
) -> Tuple[str, Dict[str, Any]]:
    """Raw LLM completion for judging — deliberately NOT routed through the
    AI-summary templates (which would reframe the rubric as a search query).

    Returns ``(reply_text, usage)`` where ``usage`` is the token-usage payload
    from ``summarize_usage_metadata`` so judge calls are cost-tracked.
    """
    from langchain_core.callbacks import UsageMetadataCallbackHandler
    from langchain_core.messages import HumanMessage, SystemMessage

    from ui.backend.services.llm_service import summarize_usage_metadata
    from utils.llm_factory import get_llm

    llm = get_llm(model=model_key, temperature=0.0, max_tokens=300)
    usage_handler = UsageMetadataCallbackHandler()
    response = await llm.ainvoke(
        [
            SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ],
        config={"callbacks": [usage_handler]},
    )
    return str(response.content), summarize_usage_metadata(usage_handler, model_key)


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
        # Judge the raw AI summary; references + search results are context only.
        summary = str(output.get("raw_summary") or output.get("summary") or "")
        refs_text = _format_judge_references(output.get("references") or [])
        context = _format_judge_context(output)
        verdicts: Dict[str, Tuple[float, str, str]] = {}
        for assertion in expectations:
            if assertion.get("type") != "llm_judge":
                continue
            rubric = str(assertion.get("rubric", ""))
            if rubric in verdicts:
                continue
            user_prompt = (
                "Judge the AI SUMMARY below against the RUBRIC. The REFERENCES "
                "and SEARCH RESULTS are context only (NOT part of the summary).\n\n"
                "================== RUBRIC ==================\n"
                f"{rubric}\n\n"
                "============ AI SUMMARY (judge THIS) ============\n"
                f"{summary}\n\n"
                "==== REFERENCES (cited docs — NOT part of the summary) ====\n"
                f"{refs_text}\n\n"
                "== SEARCH RESULTS (sources for grounding — NOT the summary) ==\n"
                f"{context}\n\n"
                'Respond with ONLY the JSON object {"score": <0.0-1.0>, '
                '"reason": "..."}.'
            )
            full_prompt = f"SYSTEM:\n{_JUDGE_SYSTEM_PROMPT}\n\nUSER:\n{user_prompt}"
            logger.info("[LLM judge] model=%s rubric=%r", model_key, rubric[:300])
            judged, judge_usage = await _judge_call(user_prompt, model_key)
            logger.info("[LLM judge] response=%r", judged[:400])
            if judge_usage and isinstance(output, dict):
                # Stash judge usage on the case output so it is persisted in
                # actual_output and rolled into the case's token totals.
                output.setdefault("judge_usage", []).append(judge_usage)
            score, reason = _parse_judgement(judged)
            verdicts[rubric] = (score, reason, full_prompt)
        return lambda _text, rubric: verdicts.get(str(rubric), (0.0, "", ""))

    return factory


# ---------------------------------------------------------------------------
# Per-case evaluation (testable with an injected runner/judge factory)
# ---------------------------------------------------------------------------


_NO_CASE_USAGE = {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}


def _case_usage_totals(output: Any) -> Dict[str, Any]:
    """Combine a case's summary + judge usage into per-case token/cost totals.

    Cost is summed per LLM call from each call's own model rate (summary and
    judge models can differ), so mixed-model cases stay accurate. All values
    are None when the case made no LLM calls (e.g. search-only experiments).

    Monitoring only: a malformed usage payload must never fail a case that
    ran successfully, so unexpected errors are logged and yield None totals.
    """
    from ui.backend.utils.llm_costs import compute_cost

    try:
        entries: List[Dict[str, Any]] = []
        if isinstance(output, dict):
            if isinstance(output.get("usage"), dict):
                entries.append(output["usage"])
            entries.extend(
                e for e in output.get("judge_usage") or [] if isinstance(e, dict)
            )
        prompt = sum(int(e.get("prompt_tokens") or 0) for e in entries)
        completion = sum(int(e.get("completion_tokens") or 0) for e in entries)
        costs = []
        for e in entries:
            cost = compute_cost(
                e.get("llm_model"), e.get("prompt_tokens"), e.get("completion_tokens")
            )
            if cost is not None:
                costs.append(cost)
        return {
            "prompt_tokens": prompt or None,
            "completion_tokens": completion or None,
            "cost_usd": sum(costs) if costs else None,
        }
    except Exception:
        logger.warning("Failed to total case LLM usage", exc_info=True)
        return dict(_NO_CASE_USAGE)


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
            **_NO_CASE_USAGE,
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
        # Judge usage is stashed on the output by the judge factory, so the
        # totals must be computed after the judge has run.
        **_case_usage_totals(output),
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
         "cases": {case_id: {"active": bool, "cols": [bool, ...],
                             "ovr": [str, ...]}}}

    Inactive or unknown cases return ``(False, [])`` and are skipped by the
    runner. Only assertion columns whose aligned ``cols`` flag is true (and that
    reference a real column) are returned. For an ``llm_judge`` column, a
    non-empty per-cell override in ``ovr`` replaces that case's rubric.
    """
    matrix = case_expectations or {}
    columns = matrix.get("columns") or []
    state = (matrix.get("cases") or {}).get(case_id)
    if not isinstance(state, dict) or not state.get("active", False):
        return False, []
    cols = state.get("cols") or []
    overrides = state.get("ovr") or []
    assertions: List[Dict[str, Any]] = []
    for i, enabled in enumerate(cols):
        if not enabled or i >= len(columns) or not isinstance(columns[i], dict):
            continue
        assertion = columns[i]
        override = overrides[i] if i < len(overrides) else None
        if (
            assertion.get("type") == "llm_judge"
            and isinstance(override, str)
            and override.strip()
        ):
            assertion = {**assertion, "rubric": override.strip()}
        assertions.append(assertion)
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


def _progress_stats(completed: int, total: int) -> Dict[str, Any]:
    """A lightweight progress marker stored in a run's ``summary_stats`` while it
    is in flight, so the polling UI can show "completed of total cases".

    It is replaced by the real aggregate stats (``compute_summary_stats``) once
    the run finishes, so a running run never carries pass/score numbers.
    """
    return {"progress": {"completed": completed, "total": total}}


def _active_case_plan(
    matrix: Dict[str, Any], cases: List[TestCase]
) -> List[Tuple[TestCase, List[Dict[str, Any]]]]:
    """Resolve the cases that will actually run and the assertions each needs.

    Building the plan up front lets the runner publish a total case count for
    progress reporting before it starts executing.
    """
    plan: List[Tuple[TestCase, List[Dict[str, Any]]]] = []
    for case in cases:
        active, assertions = _resolve_case_plan(matrix, str(case.id))
        if active:
            plan.append((case, assertions))
    return plan


def _build_result_row(
    experiment: TestExperiment, run: TestRun, case: TestCase, outcome: Dict[str, Any]
) -> TestResult:
    """Build a compact, JSON-safe ``TestResult`` for one evaluated case.

    The full output can carry datetimes and be megabytes large; assertions have
    already run against it, so only a trimmed, serialisable copy is persisted.
    """
    stored = dict(outcome)
    stored["actual_output"] = _storable_output(outcome.get("actual_output"))
    stored["assertion_results"] = _json_safe(outcome.get("assertion_results"))
    return TestResult(
        experiment_id=experiment.id,
        run_id=run.id,
        test_case_id=case.id,
        **stored,
    )


async def _record_run_usage(
    experiment: TestExperiment, run: TestRun, dataset: TestDataset, cfg: Dict[str, Any]
) -> None:
    """Mirror a finished run's token totals into a ``user_activity`` row.

    One aggregated row per run (keyed by the run's own id), typed
    ``evaluation`` and attributed to the user who triggered the run, so the
    admin Token Usage rollup includes evaluation spend without flooding the
    activity list with per-case rows. Cost is the per-call-accurate total
    from ``summary_stats``, not recomputed from the summed token counts.

    Monitoring only: called after the run has already been committed as
    completed — a recording failure must never flip that run to failed, so
    errors are logged and swallowed.
    """
    from decimal import Decimal

    from ui.backend.services.usage_recorder import record_llm_usage

    try:
        stats = run.summary_stats or {}
        usage = {
            "llm_model": cfg.get("summary_model") or cfg.get("judge_model"),
            "prompt_tokens": stats.get("prompt_tokens"),
            "completion_tokens": stats.get("completion_tokens"),
        }
        cost = stats.get("cost_usd")
        await record_llm_usage(
            usage=usage,
            activity_type="evaluation",
            query=f"Evaluation: {experiment.name} (run {run.run_number})",
            user_id=run.created_by_user_id,
            search_id=run.id,
            server_owned=True,
            filters_extra={
                "experiment_id": str(experiment.id),
                "experiment_name": experiment.name,
                "run_id": str(run.id),
                "run_number": run.run_number,
                "data_source": dataset.data_source,
                "cases": stats.get("total"),
            },
            cost_usd=Decimal(str(cost)) if cost is not None else None,
        )
    except Exception:
        logger.warning("Failed to record evaluation run usage", exc_info=True)


async def _execute(
    session, experiment: TestExperiment, triggered_by_user_id=None
) -> None:
    dataset = await session.get(TestDataset, experiment.dataset_id)
    started = time.time()
    # Each execution is a new run; prior runs and their results are preserved.
    # The run is attributed to whoever clicked Run (falling back to the
    # experiment's creator for programmatic invocations) so token usage is
    # charged to the actual spender.
    run = TestRun(
        experiment_id=experiment.id,
        run_number=await _next_run_number(session, experiment.id),
        status=EXPERIMENT_RUNNING,
        started_at=_utcnow(),
        created_by_user_id=triggered_by_user_id or experiment.created_by_user_id,
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
    # models, then overlay any "run as group" settings, so the run matches the
    # search UI / that group's configuration.
    config = await _apply_group(session, effective_config(experiment.config))
    try:
        runner = build_case_runner(dataset.capability, config, dataset.data_source)
    except Exception as exc:
        logger.exception("Failed to build case runner")
        await _fail_run(session, experiment, run, str(exc))
        return
    judge_factory = make_judge_factory(config)
    matrix = experiment.case_expectations or {}

    # Resolve the active cases up front so the total is known, then publish
    # progress (and stream each result) as the run advances. Committing per case
    # — safe because the session is created with expire_on_commit=False — lets
    # the polling UI report how far along the run is instead of a blind "running".
    plan = _active_case_plan(matrix, await _load_cases(session, dataset.id))
    total = len(plan)
    run.summary_stats = _progress_stats(0, total)
    await session.commit()

    case_results: List[Dict[str, Any]] = []
    for completed, (case, assertions) in enumerate(plan, start=1):
        outcome = await evaluate_case(case.input, assertions, runner, judge_factory)
        case_results.append(outcome)
        session.add(_build_result_row(experiment, run, case, outcome))
        run.summary_stats = _progress_stats(completed, total)
        await session.commit()

    run.summary_stats = compute_summary_stats(
        case_results, int((time.time() - started) * 1000)
    )
    run.status = EXPERIMENT_COMPLETED
    run.finished_at = _utcnow()
    _mirror_run_to_experiment(experiment, run)
    await session.commit()
    await _record_run_usage(experiment, run, dataset, config)


async def recover_orphaned_runs(session_factory=None) -> None:
    """Fail any runs/experiments still marked running/pending.

    Runs execute as in-process background tasks that do NOT survive an api
    restart (deploy, crash, OOM). On startup any such row is therefore orphaned
    — mark it failed so the UI never shows a permanently "running" run.
    """
    factory = session_factory or async_session_factory
    message = "api restarted mid-run (orphaned background task)"
    active = [EXPERIMENT_RUNNING, EXPERIMENT_PENDING]
    try:
        async with factory() as session:
            result = await session.execute(
                update(TestRun)
                .where(TestRun.status.in_(active))
                .values(
                    status=EXPERIMENT_FAILED,
                    finished_at=_utcnow(),
                    summary_stats={"error": message},
                )
            )
            await session.execute(
                update(TestExperiment)
                .where(TestExperiment.status.in_(active))
                .values(status=EXPERIMENT_FAILED)
            )
            await session.commit()
            recovered = getattr(result, "rowcount", 0) or 0
            if recovered:
                logger.info("Recovered %s orphaned test run(s)", recovered)
    except Exception:
        logger.exception("Failed to recover orphaned test runs")


async def run_experiment(
    experiment_id, session_factory=None, triggered_by_user_id=None
) -> None:
    """Background entrypoint: load the experiment and execute one run of it.

    ``triggered_by_user_id`` is the admin who clicked Run (captured at the
    route boundary before the request context is gone) — the run and its
    token usage are attributed to them.
    """
    factory = session_factory or async_session_factory
    async with factory() as session:
        experiment = await session.get(TestExperiment, experiment_id)
        if experiment is None:
            logger.error("run_experiment: experiment %s not found", experiment_id)
            return
        try:
            await _execute(session, experiment, triggered_by_user_id)
        except Exception:
            logger.exception("Experiment %s failed unexpectedly", experiment_id)
            await _mark_failed(session, experiment, "Experiment failed")
