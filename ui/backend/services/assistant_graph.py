"""
LangGraph research assistant using deepagents.

Uses LangChain's deepagents create_agent for a focused research loop:
  - Custom search tool for Qdrant document database
  - Autonomous multi-round search and synthesis
"""

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from deepagents import create_deep_agent
from deepagents.graph import create_agent
from jinja2 import Environment, FileSystemLoader
from langchain_core.tools import tool

from ui.backend.services.search import map_field_to_storage, search_chunks

logger = logging.getLogger(__name__)

# Jinja2 environment for prompt templates
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)


def _format_search_result(r: Any) -> Dict[str, Any]:
    """Format a Qdrant ScoredPoint into a plain dict."""
    payload = r.payload if hasattr(r, "payload") else r
    # Qdrant payloads use "map_title"; fall back to "title" for tests/dicts
    title = payload.get("map_title") or payload.get("title") or "Untitled"
    # Qdrant stores page number as "sys_page_num"; fall back to "page_num"
    # for tests/dicts that use the shorter name.
    page = payload.get("sys_page_num") or payload.get("page_num")
    return {
        "chunk_id": getattr(r, "id", payload.get("chunk_id", "")),
        "doc_id": payload.get("doc_id", ""),
        "title": title,
        "text": payload.get("text", ""),
        "score": getattr(r, "score", payload.get("score", 0.0)),
        "page": page,
        "headings": payload.get("headings", []),
    }


class SearchTracker:
    """Track search calls and accumulate results for source extraction."""

    MAX_SEARCHES = 4  # Hard limit — after this, searches return a stop message

    def __init__(
        self,
        data_source: Optional[str] = None,
        reranker_model: Optional[str] = None,
        search_settings: Optional[Dict[str, Any]] = None,
    ):
        self.data_source = data_source
        self.reranker_model = reranker_model
        self.search_settings = search_settings or {}
        self.per_query: List[Dict[str, Any]] = []
        self.all_results: List[Dict[str, Any]] = []
        self._seen_ids: set = set()
        self._emitted_query_count: int = 0
        self._global_result_count: int = 0
        # Field boost state — lazily initialised on first search
        self._field_boost_fields = self.search_settings.get("field_boost_fields")
        self._field_boost_enabled = bool(
            self.search_settings.get("field_boost_enabled") and self._field_boost_fields
        )
        self._known_values: Optional[Dict[str, List[str]]] = None
        # Real-time event queue for streaming search progress
        self._event_queue: Optional[asyncio.Queue] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_queue(
        self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
    ) -> None:
        """Attach an asyncio Queue for real-time search progress events.

        Since the search tool runs synchronously (possibly in a thread),
        events are pushed via ``loop.call_soon_threadsafe``.
        """
        self._event_queue = queue
        self._event_loop = loop

    def _build_search_kwargs(self) -> Dict[str, Any]:
        """Build kwargs for search_chunks from search settings."""
        kwargs: Dict[str, Any] = {}
        s = self.search_settings
        # Exclude field_boost keys — handled separately in _apply_field_boost
        _skip = {"field_boost_enabled", "field_boost_fields"}
        mapping = {
            "dense_weight": "dense_weight",
            "recency_boost": "recency_boost",
            "recency_weight": "recency_weight",
            "recency_scale_days": "recency_scale_days",
            "section_types": "section_types",
            "keyword_boost_short_queries": "keyword_boost_short_queries",
            "min_chunk_size": "min_chunk_size",
        }
        for key, kwarg in mapping.items():
            if key not in _skip and s.get(key) is not None:
                kwargs[kwarg] = s[key]
        return kwargs

    def _resolve_known_values(self) -> Dict[str, List[str]]:
        """Lazily resolve known facet values for field boost.

        Maps abstract field names (e.g. "country") to their Qdrant storage
        names (e.g. "map_country") before querying facets — matching the
        behaviour of the search route.
        """
        if self._known_values is not None:
            return self._known_values
        self._known_values = {}
        if not self._field_boost_fields:
            return self._known_values
        try:
            from ui.backend.utils.app_state import get_db_for_source

            db = get_db_for_source(self.data_source)
            for field in self._field_boost_fields:
                storage_field = map_field_to_storage(field)
                raw = db.facet_documents(
                    key=storage_field,
                    filter_conditions=None,
                    limit=2000,
                    exact=False,
                )
                vals: List[str] = []
                for rv in raw:
                    if rv is None or rv == "":
                        continue
                    s = str(rv)
                    parts = [p.strip() for p in s.split(",")] if "," in s else [s]
                    vals.extend(p for p in parts if p)
                self._known_values[field] = vals
            logger.info(
                "Resolved field boost known values for %d fields",
                len(self._known_values),
            )
        except Exception as exc:
            logger.warning("Failed to resolve field boost values: %s", exc)
            self._field_boost_enabled = False
        return self._known_values

    @staticmethod
    def _wrap_for_field_boost(results: List) -> List:
        """Wrap raw Qdrant ScoredPoints for ``apply_field_boost``.

        ``apply_field_boost`` expects objects with ``.metadata``,
        ``.text``, ``.title``, ``.organization``, and ``.score``
        attributes (the ``SearchResult`` interface).  Raw Qdrant
        ScoredPoints have ``.payload`` / ``.score`` / ``.id`` instead.
        """
        wrapped: List = []
        for r in results:
            payload = r.payload if hasattr(r, "payload") else r
            w = SimpleNamespace(
                _original=r,
                payload=payload,
                id=getattr(r, "id", None),
                metadata=dict(payload),
                text=payload.get("text", ""),
                title=(payload.get("map_title") or payload.get("title") or ""),
                organization=payload.get("map_organization", ""),
                score=getattr(r, "score", 0.0),
            )
            wrapped.append(w)
        return wrapped

    def _apply_field_boost(self, results: List, query: str) -> List:
        """Apply field boost to raw search results if enabled.

        Wraps Qdrant ScoredPoints with lightweight adapters so that
        ``apply_field_boost`` (which expects a ``SearchResult``-like
        interface) can access ``.metadata``, ``.text``, etc.
        """
        if not self._field_boost_enabled or not self._field_boost_fields:
            return results
        known = self._resolve_known_values()
        if not known:
            return results
        try:
            from ui.backend.services.search_models import apply_field_boost

            wrapped = self._wrap_for_field_boost(results)
            boosted = apply_field_boost(wrapped, query, self._field_boost_fields, known)
            return boosted
        except Exception as exc:
            logger.warning("Field boost failed: %s", exc)
            return results

    @staticmethod
    def _enrich_from_postgres(
        formatted: List[Dict[str, Any]], data_source: Optional[str]
    ) -> None:
        """Fill in page numbers, bounding boxes and headings from PostgreSQL.

        Qdrant payloads don't store page numbers or bounding boxes — they
        live in the PostgreSQL ``chunks`` table.  This mirrors what the
        search route does via ``_build_chunk_cache``.
        """
        chunk_ids = [r["chunk_id"] for r in formatted if r.get("chunk_id")]
        if not chunk_ids:
            return
        try:
            from ui.backend.utils.app_state import get_pg_for_source

            pg = get_pg_for_source(data_source)
            chunk_cache = pg.fetch_chunks(chunk_ids)
            for r in formatted:
                cid = r["chunk_id"]
                if cid not in chunk_cache:
                    continue
                pg_chunk = chunk_cache[cid]
                if not r.get("text"):
                    r["text"] = pg_chunk.get("sys_text", "")
                if not r.get("page"):
                    r["page"] = pg_chunk.get("sys_page_num")
                if not r.get("bbox"):
                    r["bbox"] = pg_chunk.get("sys_bbox")
                if not r.get("headings"):
                    r["headings"] = pg_chunk.get("sys_headings") or []
        except Exception as exc:
            logger.warning("Failed to enrich chunk data from Postgres: %s", exc)

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Execute search, track results, return formatted dicts.

        Each result is assigned a global index that persists across
        multiple search calls so the LLM can cite results unambiguously.
        Enforces a hard search limit to prevent slow runaway loops.
        """
        if len(self.per_query) >= self.MAX_SEARCHES:
            logger.warning(
                "Search limit reached (%d). Refusing query: %s",
                self.MAX_SEARCHES,
                query,
            )
            return []

        try:
            extra_kwargs = self._build_search_kwargs()
            raw = search_chunks(
                query=query,
                limit=20,
                data_source=self.data_source,
                rerank=bool(self.reranker_model),
                rerank_model=self.reranker_model,
                **extra_kwargs,
            )
            raw = self._apply_field_boost(raw, query)
            formatted = [_format_search_result(r) for r in raw]
            self._enrich_from_postgres(formatted, self.data_source)
        except Exception as exc:
            logger.error("Search failed for query %r: %s", query, exc)
            formatted = []

        # Build result cards (title + snippet) for UI display
        result_cards = []
        for r in formatted[:10]:
            text = r.get("text", "")
            result_cards.append(
                {
                    "title": r.get("title", "Untitled"),
                    "text": (text[:150] + "...") if len(text) > 150 else text,
                }
            )

        self.per_query.append(
            {
                "query": query,
                "result_count": len(formatted),
                "results": result_cards,
            }
        )

        for r in formatted:
            cid = r.get("chunk_id", "")
            if cid not in self._seen_ids:
                self._global_result_count += 1
                r["global_index"] = self._global_result_count
                self.all_results.append(r)
                self._seen_ids.add(cid)

        # Push real-time search event (thread-safe for deep mode)
        if self._event_queue is not None and self._event_loop is not None:
            event = {
                "type": "search_status",
                "queries": [
                    {
                        "query": query,
                        "result_count": len(formatted),
                        "results": result_cards,
                    }
                ],
                "total_results": len(self.all_results),
            }
            self._emitted_query_count = len(self.per_query)
            try:
                self._event_loop.call_soon_threadsafe(
                    self._event_queue.put_nowait, event
                )
            except Exception as exc:
                logger.warning("Failed to push search event to queue: %s", exc)

        return formatted

    def get_new_queries(self) -> List[Dict[str, Any]]:
        """Return only queries not yet emitted, advancing the cursor."""
        new = self.per_query[self._emitted_query_count :]
        self._emitted_query_count = len(self.per_query)
        return new

    def get_sources(self) -> List[Dict[str, Any]]:
        """Build source references from accumulated results.

        Returns all results (not deduplicated by doc_id) so that each
        global citation index maps to exactly one entry.  Results are
        ordered by their global index so the frontend can look up
        ``sources[N-1]`` for citation ``[N]``.
        """
        ordered = sorted(
            self.all_results,
            key=lambda x: x.get("global_index", 0),
        )
        sources: List[Dict[str, Any]] = []
        for r in ordered:
            text = r.get("text", "")
            entry: Dict[str, Any] = {
                "chunkId": r.get("chunk_id", ""),
                "docId": r.get("doc_id", ""),
                "title": r.get("title", ""),
                "text": (text[:200] + "...") if len(text) > 200 else text,
                "score": r.get("score", 0.0),
                "page": r.get("page"),
                "index": r.get("global_index"),
                "headings": r.get("headings", []),
            }
            if r.get("bbox"):
                entry["bbox"] = r["bbox"]
            sources.append(entry)
        return sources


def _build_search_tool(tracker: SearchTracker):
    """Create a search tool that uses the given tracker."""

    @tool
    def search_documents(query: str) -> str:
        """Search the document database for information relevant to the query.

        Use this tool to find evidence, facts, and insights from indexed
        documents. Each result includes a document title, text excerpt, and
        relevance score. Call this tool multiple times with different queries
        to gather comprehensive evidence before writing your response.

        Args:
            query: The search query — be specific and focused for best results.
        """
        if len(tracker.per_query) >= tracker.MAX_SEARCHES:
            return (
                "SEARCH LIMIT REACHED. You have already searched "
                f"{len(tracker.per_query)} times. Stop searching and "
                "write your answer now using the results you already have."
            )

        results = tracker.search(query)

        if not results:
            return "No results found for this query."

        lines = []
        for r in results:
            idx = r.get("global_index", "?")
            title = r.get("title", "Untitled")
            text = r.get("text", "")
            lines.append(f"[{idx}] {title}\n{text}\n---")

        return f"Found {len(results)} results:\n\n" + "\n".join(lines)

    return search_documents


def _load_system_prompt(data_source: Optional[str] = None) -> str:
    """Load and render the assistant system prompt."""
    template = _jinja_env.get_template("assistant_system.j2")
    return template.render(data_source=data_source)


def build_research_agent(
    llm,
    data_source: Optional[str] = None,
    reranker_model: Optional[str] = None,
    search_settings: Optional[Dict[str, Any]] = None,
    system_prompt_override: Optional[str] = None,
) -> tuple:
    """
    Build a deep research agent.

    Args:
        llm: LangChain chat model instance
        data_source: Optional data source to restrict search
        reranker_model: Optional reranker model key from UI model combo
        search_settings: Optional search parameters (dense_weight, boosts, etc.)
        system_prompt_override: Optional group prompt to append to base prompt

    Returns:
        Tuple of (compiled_agent, search_tracker)
    """
    tracker = SearchTracker(
        data_source=data_source,
        reranker_model=reranker_model,
        search_settings=search_settings,
    )
    search_tool = _build_search_tool(tracker)
    system_prompt = _load_system_prompt(data_source)

    if system_prompt_override:
        system_prompt = (
            system_prompt
            + "\n\n## Additional Instructions\n\n"
            + system_prompt_override
        )
        logger.info(
            "Appended group prompt override (%d chars) to system prompt",
            len(system_prompt_override),
        )

    agent = create_agent(
        model=llm,
        tools=[search_tool],
        system_prompt=system_prompt,
    )

    logger.info("Built research agent for data_source=%s", data_source)
    return agent, tracker


def _load_deep_research_prompt(data_source: Optional[str] = None) -> str:
    """Load and render the deep research coordinator prompt."""
    template = _jinja_env.get_template("assistant_deep_research_coordinator.j2")
    return template.render(data_source=data_source)


def _load_researcher_prompt(data_source: Optional[str] = None) -> str:
    """Load and render the deep research researcher sub-agent prompt."""
    template = _jinja_env.get_template("assistant_deep_research_researcher.j2")
    return template.render(data_source=data_source)


def build_deep_research_agent(
    llm,
    data_source: Optional[str] = None,
    reranker_model: Optional[str] = None,
    search_settings: Optional[Dict[str, Any]] = None,
    system_prompt_override: Optional[str] = None,
) -> tuple:
    """Build a deep research agent with sub-agent delegation.

    Uses create_deep_agent with a researcher sub-agent that has access
    to the search_documents tool.  The coordinator plans and synthesizes
    while the researcher executes searches.

    Returns:
        Tuple of (compiled_agent, search_tracker)
    """
    tracker = SearchTracker(
        data_source=data_source,
        reranker_model=reranker_model,
        search_settings=search_settings,
    )
    # Allow more searches in deep mode
    tracker.MAX_SEARCHES = 12

    search_tool = _build_search_tool(tracker)

    coordinator_prompt = _load_deep_research_prompt(data_source)
    researcher_prompt = _load_researcher_prompt(data_source)

    if system_prompt_override:
        coordinator_prompt = (
            coordinator_prompt
            + "\n\n## Additional Instructions\n\n"
            + system_prompt_override
        )
        logger.info(
            "Appended group prompt override (%d chars) to deep "
            "research coordinator prompt",
            len(system_prompt_override),
        )

    researcher_subagent: Dict[str, Any] = {
        "name": "researcher",
        "description": (
            "Conducts thorough searches of the document database "
            "using multiple diverse queries. Give it a broad research "
            "brief and it will search from many angles, returning "
            "comprehensive findings with citation numbers."
        ),
        "system_prompt": researcher_prompt,
        "tools": [search_tool],
    }

    agent = create_deep_agent(
        model=llm,
        tools=[],
        system_prompt=coordinator_prompt,
        subagents=[researcher_subagent],
    )

    logger.info("Built deep research agent for data_source=%s", data_source)
    return agent, tracker
