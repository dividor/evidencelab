"""Unit tests for Assistant searching and citation tracking."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ui.backend.services.assistant_graph import (
    SearchTracker,
    _format_search_result,
    _spread_across_documents,
    build_research_agent,
)
from ui.backend.services.assistant_service import (
    _extract_prior_sources,
    stream_research_response,
)

_mock_search_fn = MagicMock(return_value=[])
_mock_search_models = ModuleType("ui.backend.services.search_models")
_mock_apply_field_boost = MagicMock(side_effect=lambda r, *a, **kw: r)
_mock_search_models.apply_field_boost = _mock_apply_field_boost


class _FakeScoredPoint:
    """Mimics a Qdrant ScoredPoint for testing."""

    def __init__(self, id, score, payload):
        self.id = id
        self.score = score
        self.payload = payload


def _make_scored_point(chunk_id, doc_id, title="Doc", text="T", score=0.9, **extra):
    payload = {"doc_id": doc_id, "title": title, "text": text, **extra}
    return _FakeScoredPoint(id=chunk_id, score=score, payload=payload)


class TestFormatSearchResult:
    """Tests for _format_search_result."""

    def test_formats_scored_point(self):
        point = _make_scored_point("c1", "d1", "Title", "Content", 0.85)
        result = _format_search_result(point)

        assert result["chunk_id"] == "c1"
        assert result["doc_id"] == "d1"
        assert result["title"] == "Title"
        assert result["text"] == "Content"
        assert result["score"] == 0.85

    def test_extracts_sys_page_num(self):
        """page should come from sys_page_num (Qdrant convention)."""
        point = _make_scored_point("c1", "d1", sys_page_num=5)
        result = _format_search_result(point)
        assert result["page"] == 5

    def test_falls_back_to_page_num(self):
        """page should fall back to page_num for tests/dicts."""
        point = _make_scored_point("c1", "d1", page_num=3)
        result = _format_search_result(point)
        assert result["page"] == 3

    def test_page_none_when_missing(self):
        """page should be None when neither field is present."""
        point = _make_scored_point("c1", "d1")
        result = _format_search_result(point)
        assert result["page"] is None

    def test_handles_dict_input(self):
        data = {
            "chunk_id": "c1",
            "doc_id": "d1",
            "title": "Title",
            "text": "Content",
            "score": 0.9,
        }
        result = _format_search_result(data)

        assert result["doc_id"] == "d1"
        assert result["title"] == "Title"


@patch("ui.backend.services.assistant_graph.search_chunks", new=_mock_search_fn)
class TestSearchTracker:
    """Tests for the SearchTracker class."""

    def test_search_tracks_results(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc 1", "Content", 0.9),
            _make_scored_point("c2", "d2", "Doc 2", "Content", 0.8),
        ]

        tracker = SearchTracker(data_source="test")
        results = tracker.search("food security")

        assert len(results) == 2
        assert len(tracker.all_results) == 2
        assert len(tracker.per_query) == 1
        assert tracker.per_query[0]["query"] == "food security"
        assert tracker.per_query[0]["result_count"] == 2

    def test_deduplicates_across_queries(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = [
            [_make_scored_point("c1", "d1", score=0.9)],
            [
                _make_scored_point("c1", "d1", score=0.9),
                _make_scored_point("c2", "d2", score=0.8),
            ],
        ]

        tracker = SearchTracker()
        tracker.search("query 1")
        tracker.search("query 2")

        # c1 should appear only once even though returned by both queries
        assert len(tracker.all_results) == 2
        chunk_ids = [r["chunk_id"] for r in tracker.all_results]
        assert chunk_ids.count("c1") == 1

    def test_tracks_multiple_queries(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = [
            [_make_scored_point("c1", "d1", score=0.9)],
            [_make_scored_point("c2", "d2", score=0.8)],
        ]

        tracker = SearchTracker()
        tracker.search("query 1")
        tracker.search("query 2")

        assert len(tracker.per_query) == 2
        assert tracker.per_query[0]["query"] == "query 1"
        assert tracker.per_query[1]["query"] == "query 2"

    def test_search_error_reaches_caller(self):
        with patch(
            "ui.backend.services.assistant_graph.search_chunks",
            side_effect=RuntimeError("Search is down"),
        ), pytest.raises(RuntimeError, match="Search is down"):
            SearchTracker(data_source="wfp").search("nutrition")

    def test_get_sources_returns_all_results_by_index(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc A", "Text 1", 0.9),
            _make_scored_point("c2", "d1", "Doc A", "Text 2", 0.8),
            _make_scored_point("c3", "d2", "Doc B", "Text 3", 0.7),
        ]

        tracker = SearchTracker()
        tracker.search("query")
        sources = tracker.get_sources()

        # All results preserved (not deduped by doc_id) for citation mapping
        assert len(sources) == 3
        assert sources[0]["index"] == 1
        assert sources[1]["index"] == 2
        assert sources[2]["index"] == 3

    def test_get_sources_ordered_by_global_index(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Low", "Text", 0.3),
            _make_scored_point("c2", "d2", "High", "Text", 0.9),
        ]

        tracker = SearchTracker()
        tracker.search("query")
        sources = tracker.get_sources()

        assert sources[0]["index"] == 1
        assert sources[1]["index"] == 2

    def test_get_sources_keeps_full_text(self):
        # Sources carry the complete chunk text (no truncation) so the Brief's
        # Word export can render the full excerpt for each cited source.
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        long_text = "x" * 300
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc", long_text, 0.9),
        ]

        tracker = SearchTracker()
        tracker.search("query")
        sources = tracker.get_sources()

        assert sources[0]["text"] == long_text
        assert not sources[0]["text"].endswith("...")

    def test_get_sources_emits_pdf_and_report_urls_when_present(self):
        # Document-level public links flow into the SSE source shape so the
        # Word export can point citations at the actual PDF.
        tracker = SearchTracker()
        tracker.all_results = [
            {
                "chunk_id": "c1",
                "doc_id": "d1",
                "title": "Doc",
                "text": "T",
                "score": 0.9,
                "page": 4,
                "global_index": 1,
                "pdf_url": "https://docs.example.org/WFP-1/download/",
                "report_url": "https://docs.example.org/WFP-1/report/",
            }
        ]

        sources = tracker.get_sources()

        assert sources[0]["pdfUrl"] == "https://docs.example.org/WFP-1/download/"
        assert sources[0]["reportUrl"] == "https://docs.example.org/WFP-1/report/"

    def test_get_sources_omits_link_keys_when_absent(self):
        # Older results without links must not carry empty pdfUrl/reportUrl keys.
        tracker = SearchTracker()
        tracker.all_results = [
            {
                "chunk_id": "c1",
                "doc_id": "d1",
                "title": "Doc",
                "text": "T",
                "score": 0.9,
                "page": 4,
                "global_index": 1,
            }
        ]

        sources = tracker.get_sources()

        assert "pdfUrl" not in sources[0]
        assert "reportUrl" not in sources[0]

    def test_enrich_doc_links_attaches_urls_by_doc_id(self):
        pg = MagicMock()
        pg.fetch_docs.return_value = {
            "d1": {
                "map_pdf_url": "https://docs.example.org/WFP-1/download/",
                "map_report_url": "https://docs.example.org/WFP-1/report/",
            }
        }
        formatted = [
            {"chunk_id": "c1", "doc_id": "d1"},
            {"chunk_id": "c2", "doc_id": "d2"},  # no metadata → left untouched
        ]

        with patch("ui.backend.utils.app_state.get_pg_for_source", return_value=pg):
            SearchTracker._enrich_doc_links(formatted, "wfp")

        assert formatted[0]["pdf_url"] == "https://docs.example.org/WFP-1/download/"
        assert formatted[0]["report_url"] == "https://docs.example.org/WFP-1/report/"
        assert "pdf_url" not in formatted[1]

    def test_enrich_doc_links_swallows_db_errors(self):
        # Enrichment is best-effort — a Postgres failure must not break search.
        formatted = [{"chunk_id": "c1", "doc_id": "d1"}]
        with patch(
            "ui.backend.utils.app_state.get_pg_for_source",
            side_effect=Exception("db down"),
        ):
            SearchTracker._enrich_doc_links(formatted, "wfp")
        assert "pdf_url" not in formatted[0]

    def test_global_result_numbering_across_searches(self):
        """Results should have globally unique indices across multiple searches."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = [
            [
                _make_scored_point("c1", "d1", "Doc 1", "T1", 0.9),
                _make_scored_point("c2", "d2", "Doc 2", "T2", 0.8),
            ],
            [
                _make_scored_point("c3", "d3", "Doc 3", "T3", 0.7),
            ],
        ]

        tracker = SearchTracker()
        r1 = tracker.search("query 1")
        r2 = tracker.search("query 2")

        # First search: indices 1 and 2
        assert r1[0]["global_index"] == 1
        assert r1[1]["global_index"] == 2
        # Second search: index 3 (continues from first)
        assert r2[0]["global_index"] == 3

    def test_global_index_skips_duplicates(self):
        """Duplicate results should not receive a new global index."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = [
            [_make_scored_point("c1", "d1", score=0.9)],
            [
                _make_scored_point("c1", "d1", score=0.9),  # duplicate
                _make_scored_point("c2", "d2", score=0.8),  # new
            ],
        ]

        tracker = SearchTracker()
        tracker.search("query 1")
        tracker.search("query 2")

        # Only 2 unique results, indices 1 and 2
        assert len(tracker.all_results) == 2
        assert tracker.all_results[0]["global_index"] == 1
        assert tracker.all_results[1]["global_index"] == 2

    def test_prior_sources_seed_global_index_counter(self):
        """A new turn must continue numbering from the highest prior index, not 1."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c-new", "d-new", "Fresh Doc", "T", 0.9),
        ]

        prior = [
            {"chunkId": "c1", "docId": "d1", "title": "Doc 1", "index": 1},
            {"chunkId": "c2", "docId": "d2", "title": "Doc 2", "index": 5},
            {"chunkId": "c3", "docId": "d3", "title": "Doc 3", "index": 30},
        ]
        tracker = SearchTracker(prior_sources=prior)
        results = tracker.search("follow-up query")

        # New chunk continues from prior max (30), so gets index 31.
        assert results[0]["global_index"] == 31

    def test_prior_sources_seed_dedup_set(self):
        """Re-retrieving a prior chunk in a follow-up turn must not double-count it."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c-prior", "d1", score=0.9),  # already in prior
            _make_scored_point("c-new", "d2", score=0.8),  # genuinely new
        ]

        prior = [
            {"chunkId": "c-prior", "docId": "d1", "title": "Already Cited", "index": 7},
        ]
        tracker = SearchTracker(prior_sources=prior)
        results = tracker.search("follow-up query")
        assert results[0]["global_index"] == 7

        # Only the genuinely-new chunk gets added; the prior chunk is
        # skipped by dedup. The new index continues from prior max (7+1=8).
        assert [r["chunk_id"] for r in tracker.all_results] == ["c-new"]
        assert tracker.all_results[0]["global_index"] == 8

    def test_get_sources_merges_prior_and_new_sorted_by_index(self):
        """get_sources() must return prior + new entries sorted by global index."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c-new", "d-new", "New Doc", "Body", 0.9),
        ]

        prior = [
            {"chunkId": "c1", "docId": "d1", "title": "Prior 1", "index": 1},
            {"chunkId": "c3", "docId": "d3", "title": "Prior 3", "index": 3},
        ]
        tracker = SearchTracker(prior_sources=prior)
        tracker.search("follow-up")

        sources = tracker.get_sources()
        indices = [s["index"] for s in sources]
        # 1 (prior), 3 (prior), 4 (new, since prior max was 3)
        assert indices == [1, 3, 4]
        # Prior entries preserved verbatim (camelCase shape).
        assert sources[0]["title"] == "Prior 1"
        assert sources[1]["title"] == "Prior 3"
        assert sources[2]["title"] == "New Doc"

    def test_prior_sources_default_none_keeps_existing_behavior(self):
        """Omitting prior_sources must keep single-turn behavior unchanged."""
        tracker = SearchTracker()
        assert tracker.prior_sources == []
        assert tracker._global_result_count == 0
        assert tracker._source_indices == {}

    def test_prior_sources_ignores_non_int_index(self):
        """Defensive: a malformed prior entry without int index must not break init."""
        prior = [
            {"chunkId": "c1", "docId": "d1", "title": "Bad", "index": None},
            {"chunkId": "c2", "docId": "d2", "title": "Ok", "index": 4},
        ]
        tracker = SearchTracker(prior_sources=prior)
        assert tracker._global_result_count == 4
        # Only a valid citation can be assigned to a result.
        assert tracker._source_indices == {"c2": 4}

    def test_get_new_queries_returns_only_new(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = [
            [_make_scored_point("c1", "d1", score=0.9)],
            [_make_scored_point("c2", "d2", score=0.8)],
            [_make_scored_point("c3", "d3", score=0.7)],
        ]

        tracker = SearchTracker()
        tracker.search("query 1")
        tracker.search("query 2")

        # First call returns both queries
        new = tracker.get_new_queries()
        assert len(new) == 2
        assert new[0]["query"] == "query 1"
        assert new[1]["query"] == "query 2"

        # Second call returns nothing (no new queries)
        new = tracker.get_new_queries()
        assert len(new) == 0

        # After another search, returns only the new one
        tracker.search("query 3")
        new = tracker.get_new_queries()
        assert len(new) == 1
        assert new[0]["query"] == "query 3"


@patch("ui.backend.services.assistant_graph.search_chunks", new=_mock_search_fn)
class TestSearchSettingsThreading:
    """Tests for search settings being passed through to search_chunks."""

    def test_build_search_kwargs_with_all_settings(self):
        """_build_search_kwargs should convert all settings to kwargs."""
        settings = {
            "dense_weight": 0.6,
            "recency_boost": True,
            "recency_weight": 0.3,
            "recency_scale_days": 90,
            "section_types": ["text", "table"],
            "keyword_boost_short_queries": False,
            "min_chunk_size": 200,
        }
        tracker = SearchTracker(search_settings=settings)
        kwargs = tracker._build_search_kwargs()

        assert kwargs["dense_weight"] == 0.6
        assert kwargs["recency_boost"] is True
        assert kwargs["recency_weight"] == 0.3
        assert kwargs["recency_scale_days"] == 90
        assert kwargs["section_types"] == ["text", "table"]
        assert kwargs["keyword_boost_short_queries"] is False
        assert kwargs["min_chunk_size"] == 200

    def test_build_search_kwargs_forwards_wide_search_settings(self):
        """Group-saved wide search settings must reach search_chunks."""
        settings = {"wide_search": True, "wide_group_size": 3, "wide_limit": 12}
        tracker = SearchTracker(search_settings=settings)
        kwargs = tracker._build_search_kwargs()

        assert kwargs == {"wide_search": True, "wide_group_size": 3, "wide_limit": 12}

    def test_build_search_kwargs_when_combo_settings_then_caps_rerank_and_sets_embedding(
        self,
    ):
        """The combo's reranker cap and embedding model reach search_chunks."""
        settings = {"rerank_model_page_size": 10, "embedding_model": "e5_large"}
        tracker = SearchTracker(search_settings=settings)
        kwargs = tracker._build_search_kwargs()

        assert kwargs == {"max_rerank_candidates": 10, "dense_model": "e5_large"}

    def test_build_search_kwargs_empty_settings(self):
        """Empty settings should produce empty kwargs."""
        tracker = SearchTracker(search_settings={})
        kwargs = tracker._build_search_kwargs()
        assert kwargs == {}

    def test_build_search_kwargs_none_settings(self):
        """None settings (default) should produce empty kwargs."""
        tracker = SearchTracker()
        kwargs = tracker._build_search_kwargs()
        assert kwargs == {}

    def test_build_search_kwargs_partial_settings(self):
        """Only provided settings should appear in kwargs."""
        settings = {"dense_weight": 0.5, "recency_boost": True}
        tracker = SearchTracker(search_settings=settings)
        kwargs = tracker._build_search_kwargs()

        assert kwargs == {"dense_weight": 0.5, "recency_boost": True}
        assert "recency_weight" not in kwargs
        assert "section_types" not in kwargs

    def test_search_passes_settings_to_search_chunks(self):
        """search() should pass search_settings kwargs to search_chunks."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc", "T", 0.9),
        ]

        settings = {"dense_weight": 0.7, "recency_boost": True}
        tracker = SearchTracker(data_source="test", search_settings=settings)
        tracker.search("food security")

        # Verify search_chunks was called with the extra kwargs
        call_kwargs = _mock_search_fn.call_args
        assert call_kwargs.kwargs.get("dense_weight") == 0.7
        assert call_kwargs.kwargs.get("recency_boost") is True

    def test_search_without_settings_no_extra_kwargs(self):
        """search() without settings should not pass extra kwargs."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = []

        tracker = SearchTracker(data_source="test")
        tracker.search("query")

        call_kwargs = _mock_search_fn.call_args
        assert "dense_weight" not in (call_kwargs.kwargs or {})
        assert "recency_boost" not in (call_kwargs.kwargs or {})

    @patch("ui.backend.services.assistant_graph.build_research_workflow")
    def test_build_research_agent_passes_settings(self, mock_create):
        """build_research_agent should forward search_settings to tracker."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        settings = {"dense_weight": 0.5}
        agent, tracker, budget = build_research_agent(
            llm, data_source="test", search_settings=settings
        )

        assert tracker.search_settings == settings

    @patch("ui.backend.services.assistant_graph.build_research_workflow")
    def test_build_research_agent_passes_reranker(self, mock_create):
        """build_research_agent should forward reranker_model to tracker."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        agent, tracker, budget = build_research_agent(
            llm, data_source="test", reranker_model="rerank-v3"
        )

        assert tracker.reranker_model == "rerank-v3"


class TestSystemPromptOverride:
    """Tests for system_prompt_override being appended to the base prompt."""

    @patch("ui.backend.services.assistant_graph.build_research_workflow")
    def test_override_reaches_writer_prompt(self, mock_create):
        """system_prompt_override should be appended to the base prompt."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        override = "Always format responses with bullet points."
        build_research_agent(llm, data_source="test", system_prompt_override=override)

        prompt = mock_create.call_args.args[3]
        assert "Additional group instructions" in prompt
        assert override in prompt
        # Base prompt should still be present
        assert "numbered evidence" in prompt.lower()

    @patch("ui.backend.services.assistant_graph.build_research_workflow")
    def test_no_override_uses_base_prompt_only(self, mock_create):
        """Without override, system_prompt should be the base template only."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        build_research_agent(llm, data_source="test")

        prompt = mock_create.call_args.args[3]
        assert "Additional group instructions" not in prompt
        assert "numbered evidence" in prompt.lower()

    @patch("ui.backend.services.assistant_graph.build_research_workflow")
    def test_empty_override_not_appended(self, mock_create):
        """Empty string override should not add the section."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        build_research_agent(llm, data_source="test", system_prompt_override="")

        prompt = mock_create.call_args.args[3]
        assert "Additional group instructions" not in prompt

    @patch("ui.backend.services.assistant_graph.build_research_workflow")
    def test_none_override_not_appended(self, mock_create):
        """None override should not add the section."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        build_research_agent(llm, data_source="test", system_prompt_override=None)

        prompt = mock_create.call_args.args[3]
        assert "Additional group instructions" not in prompt


class TestFieldBoost:
    """Tests for field_boost integration in SearchTracker."""

    def test_field_boost_disabled_by_default(self):
        """Field boost should be disabled when not in settings."""
        tracker = SearchTracker()
        assert tracker._field_boost_enabled is False
        assert tracker._field_boost_fields is None

    def test_field_boost_enabled_with_settings(self):
        """Field boost should be enabled when settings include it."""
        settings = {
            "field_boost_enabled": True,
            "field_boost_fields": {"country": 0.5},
        }
        tracker = SearchTracker(search_settings=settings)
        assert tracker._field_boost_enabled is True
        assert tracker._field_boost_fields == {"country": 0.5}

    def test_field_boost_disabled_without_fields(self):
        """Field boost should be disabled if enabled but no fields given."""
        settings = {"field_boost_enabled": True}
        tracker = SearchTracker(search_settings=settings)
        assert tracker._field_boost_enabled is False

    def test_field_boost_not_in_search_kwargs(self):
        """field_boost keys should not leak into search_chunks kwargs."""
        settings = {
            "field_boost_enabled": True,
            "field_boost_fields": {"country": 0.5},
            "dense_weight": 0.7,
        }
        tracker = SearchTracker(search_settings=settings)
        kwargs = tracker._build_search_kwargs()
        assert "field_boost_enabled" not in kwargs
        assert "field_boost_fields" not in kwargs
        assert kwargs["dense_weight"] == 0.7

    @patch.dict(
        sys.modules,
        {"ui.backend.services.search_models": _mock_search_models},
    )
    def test_apply_field_boost_called_when_enabled(self):
        """_apply_field_boost should call apply_field_boost with wrapped results."""
        _mock_apply_field_boost.reset_mock()
        _mock_apply_field_boost.side_effect = None
        _mock_apply_field_boost.return_value = ["boosted_result"]

        settings = {
            "field_boost_enabled": True,
            "field_boost_fields": {"country": 0.5},
        }
        tracker = SearchTracker(search_settings=settings)
        # Pre-populate known values to skip DB lookup
        tracker._known_values = {"country": ["Kenya", "Nigeria"]}

        raw_point = _FakeScoredPoint(
            id="c1", score=0.9, payload={"text": "hello", "map_title": "T"}
        )
        result = tracker._apply_field_boost([raw_point], "food security Kenya")

        _mock_apply_field_boost.assert_called_once()
        call_args = _mock_apply_field_boost.call_args
        # First arg should be wrapped results (SimpleNamespace list)
        wrapped = call_args[0][0]
        assert len(wrapped) == 1
        assert wrapped[0]._original is raw_point
        assert wrapped[0].text == "hello"
        assert wrapped[0].title == "T"
        # Other args should be passed through
        assert call_args[0][1] == "food security Kenya"
        assert call_args[0][2] == {"country": 0.5}
        assert call_args[0][3] == {"country": ["Kenya", "Nigeria"]}
        assert result == ["boosted_result"]

    def test_apply_field_boost_skipped_when_disabled(self):
        """_apply_field_boost should return results unchanged when disabled."""
        tracker = SearchTracker()
        raw = [MagicMock()]
        result = tracker._apply_field_boost(raw, "query")
        assert result == raw


@patch("ui.backend.services.assistant_graph.search_chunks", new=_mock_search_fn)
class TestGetSourcesEnrichment:
    """Tests for get_sources including bbox and headings from enrichment."""

    def test_get_sources_includes_bbox(self):
        """get_sources should include bbox when present in results."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc", "Text", 0.9),
        ]

        tracker = SearchTracker()
        tracker.search("query")
        # Simulate enrichment adding bbox (as _enrich_from_postgres does)
        tracker.all_results[0]["bbox"] = [[5, [0.1, 0.2, 0.8, 0.9]]]
        sources = tracker.get_sources()

        assert len(sources) == 1
        assert sources[0]["bbox"] == [[5, [0.1, 0.2, 0.8, 0.9]]]

    def test_get_sources_omits_bbox_when_absent(self):
        """get_sources should not include bbox key when not present."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc", "Text", 0.9),
        ]

        tracker = SearchTracker()
        tracker.search("query")
        sources = tracker.get_sources()

        assert "bbox" not in sources[0]

    def test_get_sources_includes_headings(self):
        """get_sources should include headings from enrichment."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc", "Text", 0.9),
        ]

        tracker = SearchTracker()
        tracker.search("query")
        tracker.all_results[0]["headings"] = ["Chapter 1", "Section A"]
        sources = tracker.get_sources()

        assert sources[0]["headings"] == ["Chapter 1", "Section A"]


class TestExtractPriorSources:
    """Tests for _extract_prior_sources — pulling sources from history."""

    def test_returns_empty_for_none_or_empty(self):
        assert _extract_prior_sources(None, "wfp") == []
        assert _extract_prior_sources([], "wfp") == []

    def test_extracts_sources_from_assistant_messages_only(self):
        history = [
            {
                "role": "user",
                "content": "Q1",
                "sources": [{"index": 99, "dataSource": "wfp"}],
            },
            {
                "role": "assistant",
                "content": "A1",
                "sources": [{"index": 1, "title": "T", "dataSource": "wfp"}],
            },
        ]
        result = _extract_prior_sources(history, "wfp")
        assert [s["index"] for s in result] == [1]

    def test_dedupes_across_turns_by_index(self):
        """A citation re-cited in turn 2 must appear only once."""
        history = [
            {
                "role": "assistant",
                "content": "A1",
                "sources": [
                    {"index": 1, "title": "T1", "dataSource": "wfp"},
                    {"index": 2, "title": "T2", "dataSource": "wfp"},
                ],
            },
            {"role": "user", "content": "Q2"},
            {
                "role": "assistant",
                "content": "A2",
                "sources": [
                    {
                        "index": 2,
                        "title": "T2 (latest)",
                        "dataSource": "wfp",
                    },  # duplicate index — latest wins
                    {"index": 3, "title": "T3", "dataSource": "wfp"},
                ],
            },
        ]
        result = _extract_prior_sources(history, "wfp")
        assert [s["index"] for s in result] == [1, 2, 3]
        # Last-write-wins lets the most recent message refine an entry if needed.
        assert result[1]["title"] == "T2 (latest)"

    def test_ignores_assistant_messages_without_sources(self):
        history = [
            {"role": "assistant", "content": "A1"},  # no sources key at all
            {"role": "assistant", "content": "A2", "sources": []},  # empty list
            {"role": "assistant", "content": "A3", "sources": None},  # explicit None
        ]
        assert _extract_prior_sources(history, "wfp") == []

    def test_ignores_sources_with_non_int_index(self):
        history = [
            {
                "role": "assistant",
                "content": "A1",
                "sources": [
                    {"index": "abc", "title": "Bad", "dataSource": "wfp"},
                    {"index": 2, "title": "Good", "dataSource": "wfp"},
                ],
            },
        ]
        result = _extract_prior_sources(history, "wfp")
        assert [s["index"] for s in result] == [2]


class TestSpreadAcrossDocuments:
    """Wide search returns results document by document; the assistant keeps
    its per-search budget by taking the best chunk of each document first."""

    @staticmethod
    def _point(doc_id, chunk):
        return SimpleNamespace(id=f"{doc_id}-{chunk}", payload={"doc_id": doc_id})

    def test_takes_best_chunk_of_each_document_before_second_chunks(self):
        points = (
            [self._point("a", i) for i in range(5)]
            + [self._point("b", i) for i in range(5)]
            + [self._point("c", i) for i in range(5)]
        )

        selected = _spread_across_documents(points, 5)

        assert [p.id for p in selected] == ["a-0", "b-0", "c-0", "a-1", "b-1"]

    def test_returns_everything_when_under_the_limit(self):
        points = [self._point("a", 0), self._point("a", 1), self._point("b", 0)]

        selected = _spread_across_documents(points, 20)

        assert [p.id for p in selected] == ["a-0", "b-0", "a-1"]

    def test_wide_search_results_are_spread_before_formatting(self):
        """SearchTracker.search() applies the spread only in wide mode."""
        points = [self._point("a", i) for i in range(30)] + [
            self._point("b", i) for i in range(30)
        ]
        for p in points:
            p.payload.update({"text": "t", "document_title": "d", "page_number": 1})
            p.score = 0.5
        with patch(
            "ui.backend.services.assistant_graph.search_chunks", return_value=points
        ):
            wide = SearchTracker(
                search_settings={"wide_search": True, "wide_limit": 20}
            )
            wide.search("q")
            narrow = SearchTracker(search_settings={})
            narrow.search("q")

        wide_docs = {r["doc_id"] for r in wide.all_results}
        narrow_docs = {r["doc_id"] for r in narrow.all_results}
        assert len(wide.all_results) == SearchTracker.RESULTS_PER_SEARCH
        assert wide_docs == {"a", "b"}
        assert len(narrow.all_results) == len(points)
        assert narrow_docs == {"a", "b"}


class TestResearchDataSource:
    """MCP and A2A call the research service directly, without the chat route."""

    @pytest.mark.asyncio
    async def test_research_when_no_source_among_several_then_raises(self):
        from pipeline.db import config as db_config

        with patch.object(
            db_config, "_configured_data_sources", return_value=["uneg", "worldbank"]
        ), patch.object(db_config, "DEFAULT_DATA_SOURCE", None):
            with pytest.raises(ValueError, match="Invalid data_source: none given"):
                async for _event in stream_research_response(query="q"):
                    pass

    @pytest.mark.asyncio
    async def test_research_when_source_not_in_deployment_then_raises(self):
        from ui.backend.utils import app_state

        with patch.object(app_state, "_get_valid_data_sources", return_value={"wfp"}):
            with pytest.raises(ValueError, match="Invalid data_source: uneg"):
                async for _event in stream_research_response(
                    query="q", data_source="uneg"
                ):
                    pass
