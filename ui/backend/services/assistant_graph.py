"""Search, citation tracking and workflow setup for the Research Assistant."""

import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from pipeline.utilities.text_cleaning import clean_text
from ui.backend.services.assistant_research import (
    ResearchLimits,
    build_research_workflow,
)
from ui.backend.services.assistant_settings import (
    AssistantSettings,
    assistant_prompt_templates,
    assistant_search_defaults,
)
from ui.backend.services.search import map_field_to_storage, search_chunks

logger = logging.getLogger(__name__)


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


def _spread_across_documents(points: List[Any], limit: int) -> List[Any]:
    """Keep at most ``limit`` points, taking the best chunk of each document
    first (in document order), then second chunks, and so on. Wide search
    returns results document by document, so a plain cut would keep only the
    first few documents' chunks; this keeps the coverage that wide search is
    for while respecting the tool's result budget."""
    by_doc: Dict[str, List[Any]] = {}
    for point in points:
        payload = getattr(point, "payload", None) or {}
        key = str(payload.get("doc_id") or getattr(point, "id", ""))
        by_doc.setdefault(key, []).append(point)
    queues = list(by_doc.values())
    selected: List[Any] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for queue in queues:
            if depth < len(queue) and len(selected) < limit:
                selected.append(queue[depth])
                added = True
        if not added:
            break
        depth += 1
    return selected


class SearchTracker:
    """Track search calls and accumulate results for source extraction."""

    # Results handed to the model per tool search. In wide mode the search

    # returns documents x per-document chunks; it is spread back to this many.

    RESULTS_PER_SEARCH = 20

    def __init__(
        self,
        data_source: Optional[str] = None,
        reranker_model: Optional[str] = None,
        search_settings: Optional[Dict[str, Any]] = None,
        prior_sources: Optional[List[Dict[str, Any]]] = None,
    ):
        self.data_source = data_source
        self.reranker_model = reranker_model
        self.search_settings = search_settings or {}
        self.per_query: List[Dict[str, Any]] = []
        self.all_results: List[Dict[str, Any]] = []
        self._source_indices: Dict[str, int] = {}
        self._emitted_query_count: int = 0
        self._global_result_count: int = 0
        # Sources carried over from earlier turns in this conversation, in
        # the SSE/persistence shape (camelCase: chunkId, docId, title, ...,
        # index). Seeds dedup + index counter so global_index is genuinely
        # global across the whole thread, not reset per turn.
        self.prior_sources: List[Dict[str, Any]] = list(prior_sources or [])
        for s in self.prior_sources:
            cid = s.get("chunkId")
            idx = s.get("index")
            if isinstance(idx, int) and idx > 0:
                self._global_result_count = max(self._global_result_count, idx)
                if cid:
                    self._source_indices[str(cid)] = idx
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
            "wide_search": "wide_search",
            "wide_group_size": "wide_group_size",
            "wide_limit": "wide_limit",
            "rerank_model_page_size": "max_rerank_candidates",
            "embedding_model": "dense_model",
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

    @staticmethod
    def _enrich_doc_links(
        formatted: List[Dict[str, Any]], data_source: Optional[str]
    ) -> None:
        """Attach document-level ``pdf_url`` / ``report_url`` by ``doc_id``.

        Chunk payloads only carry chunk-level fields; the public source URLs
        live on the ``documents`` row. Mirroring what the search route exposes
        via document metadata, this lets the Word export link each citation to
        the actual PDF (openable outside Evidence Lab) rather than the in-app
        deep link.
        """
        doc_ids = {r["doc_id"] for r in formatted if r.get("doc_id")}
        if not doc_ids:
            return
        try:
            from ui.backend.utils.app_state import get_pg_for_source

            pg = get_pg_for_source(data_source)
            doc_meta = pg.fetch_docs(doc_ids)
        except Exception as exc:
            logger.warning("Failed to enrich doc links from Postgres: %s", exc)
            return
        for r in formatted:
            meta = doc_meta.get(str(r.get("doc_id")))
            if not meta:
                continue
            r["pdf_url"] = meta.get("map_pdf_url")
            r["report_url"] = meta.get("map_report_url")

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search the configured collection and keep stable result numbers."""
        kwargs = self._build_search_kwargs()
        points = search_chunks(
            query=query,
            limit=self.RESULTS_PER_SEARCH,
            data_source=self.data_source,
            rerank=bool(self.reranker_model),
            rerank_model=self.reranker_model,
            **kwargs,
        )
        if kwargs.get("wide_search"):
            points = _spread_across_documents(points, self.RESULTS_PER_SEARCH)
        formatted = [
            _format_search_result(r) for r in self._apply_field_boost(points, query)
        ]
        self._enrich_from_postgres(formatted, self.data_source)
        self._enrich_doc_links(formatted, self.data_source)

        self.per_query.append(
            {
                "query": query,
                "result_count": len(formatted),
                "results": [
                    {"title": r["title"], "text": r["text"]} for r in formatted[:10]
                ],
            }
        )
        for r in formatted:
            chunk_id = str(r["chunk_id"])
            if chunk_id not in self._source_indices:
                self._global_result_count += 1
                self._source_indices[chunk_id] = self._global_result_count
                r["global_index"] = self._global_result_count
                self.all_results.append(r)
            else:
                r["global_index"] = self._source_indices[chunk_id]
        return formatted

    def get_new_queries(self) -> List[Dict[str, Any]]:
        """Return only queries not yet emitted, advancing the cursor."""
        new = self.per_query[self._emitted_query_count :]
        self._emitted_query_count = len(self.per_query)
        return new

    def get_sources(self) -> List[Dict[str, Any]]:
        """Build source references from accumulated results.

        Returns prior-turn sources merged with this turn's new results, in
        the SSE/persistence shape, ordered by global index. Including
        prior sources lets the frontend resolve citation markers carried
        over from earlier assistant messages — e.g. when a follow-up
        question asks for a summary of the previous answer without
        triggering any new search.
        """
        new_sources: List[Dict[str, Any]] = []
        for r in self.all_results:
            # Same encoding repair Search applies to chunk text and titles
            # (routes/search.py), so citation excerpts read identically.
            text = clean_text(r.get("text", ""))
            entry: Dict[str, Any] = {
                "chunkId": r.get("chunk_id", ""),
                "docId": r.get("doc_id", ""),
                "dataSource": self.data_source,
                "title": clean_text(r.get("title", "")),
                # Full chunk text (not truncated): the on-screen citation panels
                # show title/page only, while the Brief's Word export renders the
                # complete excerpt for each cited source.
                "text": text,
                "score": r.get("score", 0.0),
                "page": r.get("page"),
                "index": r.get("global_index"),
                "headings": r.get("headings", []),
            }
            if r.get("bbox"):
                entry["bbox"] = r["bbox"]
            # Public source links (document-level), so the Word export can point
            # citations at the actual PDF rather than the in-app deep link.
            if r.get("pdf_url"):
                entry["pdfUrl"] = r["pdf_url"]
            if r.get("report_url"):
                entry["reportUrl"] = r["report_url"]
            new_sources.append(entry)
        combined = list(self.prior_sources) + new_sources
        return sorted(combined, key=lambda x: x.get("index") or 0)


def build_research_agent(
    llm,
    data_source: Optional[str] = None,
    reranker_model: Optional[str] = None,
    search_settings: Optional[Dict[str, Any]] = None,
    system_prompt_override: Optional[str] = None,
    prior_sources: Optional[List[Dict[str, Any]]] = None,
    *,
    deep_research: bool = False,
    target_words: Optional[int] = None,
    introduces_sub_sections: Optional[List[str]] = None,
    assistant_settings: Optional[AssistantSettings] = None,
) -> tuple:
    """Build the same evidence workflow with the selected research budget."""
    default_searches, default_per_stream = assistant_search_defaults(deep_research)
    settings = assistant_settings or AssistantSettings()
    searches, per_stream = settings.search_limits(deep_research)
    max_queries = searches if searches is not None else default_searches
    tracker = SearchTracker(data_source, reranker_model, search_settings, prior_sources)
    template = assistant_prompt_templates.get_template("assistant_research_planner.j2")
    planner = template.render(
        deep_research=deep_research,
        group_instructions=settings.planningPrompt,
        instructions=settings.planningInstructions,
    )
    opening = template.render(
        deep_research=deep_research,
        organize=True,
        group_instructions=settings.planningPrompt,
        instructions=settings.planningInstructions,
    )
    contextualizer = template.render(
        contextualize=True,
        data_source=data_source,
        group_instructions=settings.planningPrompt,
        instructions=settings.planningInstructions,
    )
    writer = assistant_prompt_templates.get_template("assistant_system.j2").render(
        data_source=data_source,
        target_words=target_words,
        intro_sub_sections=introduces_sub_sections,
        group_instructions=(
            (settings.answerPrompt or system_prompt_override)
            if not settings.answerInstructions
            else None
        ),
        instructions=settings.answerInstructions,
        deep_research=deep_research,
    )
    limits = ResearchLimits(
        searches=max_queries,
        searches_per_stream=per_stream or default_per_stream,
    )
    agent = build_research_workflow(
        llm, tracker, planner, writer, limits, opening, contextualizer=contextualizer
    )
    return agent, tracker, max_queries
