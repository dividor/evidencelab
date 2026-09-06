"""LLM token-usage recording for pipeline stages (summarize / tag).

The admin "Token Usage" rollup reads the ``user_activity`` table, which was
historically only written from the browser — batch ingestion spend was
invisible. Pipeline stages now accumulate the token usage reported on each
LangChain response into a :class:`UsageCollector` and, once per document per
stage, write one anonymous ``user_activity`` row per model used, typed
``pipeline`` with the stage / data source / document id kept in the filters
JSONB.

The writer talks straight to the shared Postgres instance (the same
``POSTGRES_*`` environment the user module uses) with a short-lived psycopg2
connection — one insert per document per stage, so no pooling is needed.
Recording is fire-and-forget by design (mirroring the MCP audit log): an
ingestion run must never fail because usage accounting did, so errors are
logged and swallowed.
"""

import json
import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from ui.backend.utils.llm_costs import compute_cost

logger = logging.getLogger(__name__)


class UsageCollector:
    """Thread-safe accumulator of per-model token usage for one document.

    ``add_response`` reads the ``usage_metadata`` LangChain attaches to
    ``AIMessage`` responses (``{input_tokens, output_tokens, ...}``). Chunk
    summarization fans out over a thread pool, so accumulation is locked.

    Concurrency caveat: when maintenance scripts share ONE processor
    instance across document-level worker threads, per-document attribution
    becomes approximate — a flush drains whatever has accumulated so far,
    which may include another in-flight document's calls. Totals are always
    preserved (nothing is dropped or double-counted); only the doc_id label
    of concurrent flushes can be off. The pipeline workers themselves
    process documents sequentially per processor, where attribution is
    exact.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_model: Dict[str, Dict[str, int]] = {}

    def add_response(self, response: Any, model_key: Optional[str]) -> None:
        """Accumulate one LLM response's reported usage under *model_key*.

        Monitoring only: called inline from the pipeline's LLM call sites,
        so a malformed usage payload must never fail the stage — it is
        logged and skipped instead.
        """
        try:
            meta = getattr(response, "usage_metadata", None)
            if not isinstance(meta, dict):
                return
            prompt = int(meta.get("input_tokens") or 0)
            completion = int(meta.get("output_tokens") or 0)
            if not prompt and not completion:
                return
            key = model_key or "unknown"
            with self._lock:
                totals = self._by_model.setdefault(
                    key, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
                )
                totals["prompt_tokens"] += prompt
                totals["completion_tokens"] += completion
                totals["calls"] += 1
        except Exception:
            logger.warning("Failed to accumulate LLM usage", exc_info=True)

    def reset(self) -> None:
        """Drop accumulated usage (start of a new document)."""
        with self._lock:
            self._by_model = {}

    def entries(self) -> List[Dict[str, Any]]:
        """One usage dict per model: ``{llm_model, prompt_tokens, ...}``."""
        with self._lock:
            return [
                {"llm_model": model, **dict(totals)}
                for model, totals in self._by_model.items()
            ]


def _connect():
    """Open a short-lived connection to the shared (user-module) database.

    Uses the pipeline's canonical DSN builder so the in-Docker
    ``localhost`` → ``postgres`` host remap and env-var fallbacks stay in
    one place.
    """
    import psycopg2

    from pipeline.db.postgres_client_base import build_postgres_dsn

    return psycopg2.connect(build_postgres_dsn())


_INSERT_SQL = """
    INSERT INTO user_activity
        (search_id, query, filters, llm_model,
         prompt_tokens, completion_tokens, cost_usd)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def record_pipeline_usage(
    collector: UsageCollector,
    *,
    stage: str,
    data_source: Optional[str],
    doc_id: Optional[str],
    query: str,
) -> bool:
    """Write one ``user_activity`` row per model the collector saw.

    Args:
        collector: Accumulated usage for one document's stage processing.
        stage: Pipeline stage name (``summarize``, ``tag``).
        data_source: Datasource key the document belongs to.
        doc_id: Document id, kept in the filters JSONB for traceability.
        query: Row label, e.g. ``"summarize: <title>"``.

    Returns:
        True when at least one row was written.
    """
    try:
        entries = collector.entries()
        collector.reset()
        if not entries:
            return False
        conn = _connect()
        try:
            with conn.cursor() as cur:
                for entry in entries:
                    cost = compute_cost(
                        entry.get("llm_model"),
                        entry.get("prompt_tokens"),
                        entry.get("completion_tokens"),
                    )
                    filters = {
                        "type": "pipeline",
                        "stage": stage,
                        "data_source": data_source,
                        "doc_id": doc_id,
                        "calls": entry.get("calls"),
                    }
                    cur.execute(
                        _INSERT_SQL,
                        (
                            str(uuid.uuid4()),
                            query[:5000],
                            json.dumps(filters),
                            entry.get("llm_model"),
                            entry.get("prompt_tokens"),
                            entry.get("completion_tokens"),
                            cost,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:  # pragma: no cover - defensive: never break the pipeline
        logger.warning("Failed to record pipeline LLM usage", exc_info=True)
        return False
