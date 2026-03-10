"""
LangGraph research assistant using deepagents.

Uses LangChain's deepagents create_agent for a focused research loop:
  - Custom search tool for Qdrant document database
  - Autonomous multi-round search and synthesis
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from deepagents.graph import create_agent
from jinja2 import Environment, FileSystemLoader
from langchain_core.tools import tool

from ui.backend.services.search import search_chunks

logger = logging.getLogger(__name__)

# Jinja2 environment for prompt templates
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)


def _format_search_result(r: Any) -> Dict[str, Any]:
    """Format a Qdrant ScoredPoint into a plain dict."""
    payload = r.payload if hasattr(r, "payload") else r
    # Qdrant payloads use "map_title"; fall back to "title" for tests/dicts
    title = payload.get("map_title") or payload.get("title") or "Untitled"
    return {
        "chunk_id": getattr(r, "id", payload.get("chunk_id", "")),
        "doc_id": payload.get("doc_id", ""),
        "title": title,
        "text": payload.get("text", ""),
        "score": getattr(r, "score", payload.get("score", 0.0)),
        "page": payload.get("page_num", None),
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
        """Lazily resolve known facet values for field boost."""
        if self._known_values is not None:
            return self._known_values
        self._known_values = {}
        if not self._field_boost_fields:
            return self._known_values
        try:
            from ui.backend.utils.app_state import get_db_for_source

            db = get_db_for_source(self.data_source)
            for field in self._field_boost_fields:
                raw = db.facet_documents(
                    key=field, filter_conditions=None, limit=2000, exact=False
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

    def _apply_field_boost(self, results: List, query: str) -> List:
        """Apply field boost to raw search results if enabled."""
        if not self._field_boost_enabled or not self._field_boost_fields:
            return results
        known = self._resolve_known_values()
        if not known:
            return results
        try:
            from ui.backend.services.search_models import apply_field_boost

            return apply_field_boost(results, query, self._field_boost_fields, known)
        except Exception as exc:
            logger.warning("Field boost failed: %s", exc)
            return results

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
        except Exception as exc:
            logger.error("Search failed for query %r: %s", query, exc)
            formatted = []

        self.per_query.append({"query": query, "result_count": len(formatted)})

        for r in formatted:
            cid = r.get("chunk_id", "")
            if cid not in self._seen_ids:
                self._global_result_count += 1
                r["global_index"] = self._global_result_count
                self.all_results.append(r)
                self._seen_ids.add(cid)

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
            sources.append(
                {
                    "chunkId": r.get("chunk_id", ""),
                    "docId": r.get("doc_id", ""),
                    "title": r.get("title", ""),
                    "text": (text[:200] + "...") if len(text) > 200 else text,
                    "score": r.get("score", 0.0),
                    "page": r.get("page"),
                    "index": r.get("global_index"),
                }
            )
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
