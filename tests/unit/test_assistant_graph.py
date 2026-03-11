"""Unit tests for the deepagents research assistant graph."""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch  # noqa: F811 — patch used as decorator below

# ---------------------------------------------------------------------------
# Mock the heavy imports that assistant_graph pulls in transitively.
# search -> search_models -> google_vertex_reranker -> google.cloud
#
# We temporarily install lightweight mocks into sys.modules, import the
# modules under test (which capture direct references to our mock objects),
# then IMMEDIATELY remove the mocks so later test modules that are
# collected by pytest see the real modules (or get their own import errors).
# ---------------------------------------------------------------------------
_mock_search = ModuleType("ui.backend.services.search")
_mock_search_fn = MagicMock(return_value=[])
_mock_search.search_chunks = _mock_search_fn
_mock_search.map_field_to_storage = MagicMock(side_effect=lambda f: f"map_{f}")
_mock_search.CORE_FIELD_MAP = {}

_mock_search_models = ModuleType("ui.backend.services.search_models")
_mock_apply_field_boost = MagicMock(side_effect=lambda r, *a, **kw: r)
_mock_search_models.apply_field_boost = _mock_apply_field_boost

_MOCKED_KEYS = [
    "ui.backend.services.search",
    "ui.backend.services.search_models",
]
_saved = {k: sys.modules.get(k) for k in _MOCKED_KEYS}

sys.modules["ui.backend.services.search"] = _mock_search
sys.modules["ui.backend.services.search_models"] = _mock_search_models

from ui.backend.services.assistant_graph import (  # noqa: E402
    SearchTracker,
    _build_search_tool,
    _format_search_result,
    build_research_agent,
)
from ui.backend.services.assistant_service import _is_duplicate_or_subset  # noqa: E402

# Immediately restore sys.modules so other test files are not affected.
for _k in _MOCKED_KEYS:
    if _saved[_k] is not None:
        sys.modules[_k] = _saved[_k]
    else:
        sys.modules.pop(_k, None)

# Clean up package attributes that Python's import machinery set on the
# parent package — but ONLY if they still point to our mocks.  If the
# real module was already loaded (e.g. by another test file collected
# first), we must not delete it.
import ui.backend.services as _svc_pkg  # noqa: E402

for _attr, _mock_mod in [
    ("search", _mock_search),
    ("search_models", _mock_search_models),
]:
    if getattr(_svc_pkg, _attr, None) is _mock_mod:
        try:
            delattr(_svc_pkg, _attr)
        except AttributeError:
            pass


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

    def test_handles_search_error(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = Exception("Connection error")

        tracker = SearchTracker()
        results = tracker.search("bad query")

        assert results == []
        assert len(tracker.per_query) == 1
        assert tracker.per_query[0]["result_count"] == 0

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

    def test_get_sources_truncates_long_text(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        long_text = "x" * 300
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc", long_text, 0.9),
        ]

        tracker = SearchTracker()
        tracker.search("query")
        sources = tracker.get_sources()

        assert len(sources[0]["text"]) < 300
        assert sources[0]["text"].endswith("...")

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
class TestBuildSearchTool:
    """Tests for _build_search_tool."""

    def test_tool_returns_formatted_results(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", "Doc 1", "Content about food", 0.9),
        ]

        tracker = SearchTracker()
        tool_fn = _build_search_tool(tracker)
        result = tool_fn.invoke("food security")

        assert "Found 1 results" in result
        assert "[1] Doc 1" in result
        assert "Content about food" in result

    def test_tool_uses_global_numbering(self):
        """Second search call should continue numbering from first."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = [
            [_make_scored_point("c1", "d1", "Doc 1", "T1", 0.9)],
            [_make_scored_point("c2", "d2", "Doc 2", "T2", 0.8)],
        ]

        tracker = SearchTracker()
        tool_fn = _build_search_tool(tracker)

        result1 = tool_fn.invoke("query 1")
        assert "[1] Doc 1" in result1

        result2 = tool_fn.invoke("query 2")
        assert "[2] Doc 2" in result2

    def test_tool_returns_no_results_message(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = []

        tracker = SearchTracker()
        tool_fn = _build_search_tool(tracker)
        result = tool_fn.invoke("nonexistent topic")

        assert "No results found" in result

    def test_tool_tracks_via_tracker(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            _make_scored_point("c1", "d1", score=0.9),
        ]

        tracker = SearchTracker()
        tool_fn = _build_search_tool(tracker)
        tool_fn.invoke("test query")

        assert len(tracker.per_query) == 1
        assert len(tracker.all_results) == 1


class TestBuildResearchAgent:
    """Tests for build_research_agent."""

    @patch("ui.backend.services.assistant_graph.create_agent")
    def test_creates_agent_and_tracker(self, mock_create):
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        llm = MagicMock()
        agent, tracker = build_research_agent(llm, data_source="worldbank")

        assert agent is mock_agent
        assert isinstance(tracker, SearchTracker)
        assert tracker.data_source == "worldbank"

    @patch("ui.backend.services.assistant_graph.create_agent")
    def test_passes_search_tool_and_prompt(self, mock_create):
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        build_research_agent(llm, data_source="worldbank")

        # Verify create_agent was called with model, tools, system_prompt
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["model"] is llm
        assert len(call_kwargs.kwargs["tools"]) == 1
        assert "research assistant" in call_kwargs.kwargs["system_prompt"].lower()


class TestIsDuplicateOrSubset:
    """Tests for the token dedup helper in assistant_service."""

    def test_exact_match(self):
        assert _is_duplicate_or_subset("hello world", "hello world") is True

    def test_subset_match(self):
        assert _is_duplicate_or_subset("hello", "hello world foo") is True

    def test_whitespace_normalized(self):
        assert _is_duplicate_or_subset("hello  world", "hello world") is True

    def test_different_text(self):
        assert _is_duplicate_or_subset("foo bar", "hello world") is False

    def test_empty_new_text(self):
        assert _is_duplicate_or_subset("", "hello") is False

    def test_empty_prev_text(self):
        assert _is_duplicate_or_subset("hello", "") is False

    def test_both_empty(self):
        assert _is_duplicate_or_subset("", "") is False

    def test_superset_is_not_duplicate(self):
        """If new_text is LONGER than prev_text, it's not a duplicate."""
        assert _is_duplicate_or_subset("hello world foo", "hello") is False


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

    @patch("ui.backend.services.assistant_graph.create_agent")
    def test_build_research_agent_passes_settings(self, mock_create):
        """build_research_agent should forward search_settings to tracker."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        settings = {"dense_weight": 0.5}
        agent, tracker = build_research_agent(
            llm, data_source="test", search_settings=settings
        )

        assert tracker.search_settings == settings

    @patch("ui.backend.services.assistant_graph.create_agent")
    def test_build_research_agent_passes_reranker(self, mock_create):
        """build_research_agent should forward reranker_model to tracker."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        agent, tracker = build_research_agent(
            llm, data_source="test", reranker_model="rerank-v3"
        )

        assert tracker.reranker_model == "rerank-v3"


class TestSystemPromptOverride:
    """Tests for system_prompt_override being appended to the base prompt."""

    @patch("ui.backend.services.assistant_graph.create_agent")
    def test_override_appended_to_system_prompt(self, mock_create):
        """system_prompt_override should be appended to the base prompt."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        override = "Always format responses with bullet points."
        build_research_agent(llm, data_source="test", system_prompt_override=override)

        call_kwargs = mock_create.call_args.kwargs
        prompt = call_kwargs["system_prompt"]
        assert "Additional Instructions" in prompt
        assert override in prompt
        # Base prompt should still be present
        assert "research assistant" in prompt.lower()

    @patch("ui.backend.services.assistant_graph.create_agent")
    def test_no_override_uses_base_prompt_only(self, mock_create):
        """Without override, system_prompt should be the base template only."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        build_research_agent(llm, data_source="test")

        call_kwargs = mock_create.call_args.kwargs
        prompt = call_kwargs["system_prompt"]
        assert "Additional Instructions" not in prompt
        assert "research assistant" in prompt.lower()

    @patch("ui.backend.services.assistant_graph.create_agent")
    def test_empty_override_not_appended(self, mock_create):
        """Empty string override should not add the section."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        build_research_agent(llm, data_source="test", system_prompt_override="")

        call_kwargs = mock_create.call_args.kwargs
        prompt = call_kwargs["system_prompt"]
        assert "Additional Instructions" not in prompt

    @patch("ui.backend.services.assistant_graph.create_agent")
    def test_none_override_not_appended(self, mock_create):
        """None override should not add the section."""
        mock_create.return_value = MagicMock()

        llm = MagicMock()
        build_research_agent(llm, data_source="test", system_prompt_override=None)

        call_kwargs = mock_create.call_args.kwargs
        prompt = call_kwargs["system_prompt"]
        assert "Additional Instructions" not in prompt


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
