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
    _load_system_prompt,
    _next_citation_index,
    build_research_agent,
)
from ui.backend.services.assistant_service import (  # noqa: E402
    _extract_finish_diagnostics,
    _extract_prior_sources,
    _is_duplicate_or_subset,
    _is_gemini_message,
    _process_agent_output,
    _summarize_message,
)

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
        tracker.search("follow-up query")

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
        assert tracker._seen_ids == set()

    def test_prior_sources_ignores_non_int_index(self):
        """Defensive: a malformed prior entry without int index must not break init."""
        prior = [
            {"chunkId": "c1", "docId": "d1", "title": "Bad", "index": None},
            {"chunkId": "c2", "docId": "d2", "title": "Ok", "index": 4},
        ]
        tracker = SearchTracker(prior_sources=prior)
        assert tracker._global_result_count == 4
        # Both chunkIds still seed the dedup set.
        assert tracker._seen_ids == {"c1", "c2"}

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


class TestSummarizeMessage:
    """Tests for the per-message diagnostic summary used in deep-research logging."""

    def test_text_message_no_tool_calls(self):
        msg = MagicMock(spec=["content", "tool_calls"])
        msg.content = "hello world"
        msg.tool_calls = None
        s = _summarize_message(msg)
        assert s["tool_calls"] == []
        assert s["content_len"] == len("hello world")
        assert s["type"] == "MagicMock"

    def test_message_with_tool_calls(self):
        msg = MagicMock(spec=["content", "tool_calls"])
        msg.content = ""
        msg.tool_calls = [
            {"name": "search_documents", "args": {"query": "x"}},
            {"name": "task", "args": {"description": "y"}},
        ]
        s = _summarize_message(msg)
        assert s["tool_calls"] == ["search_documents", "task"]
        assert s["content_len"] == 0

    def test_missing_content_attribute(self):
        msg = MagicMock(spec=["tool_calls"])
        msg.tool_calls = None
        s = _summarize_message(msg)
        assert s["content_len"] == 0
        assert s["tool_calls"] == []

    def test_non_string_content_returns_negative_len(self):
        """Some langchain message variants store list-of-blocks in .content."""
        msg = MagicMock(spec=["content", "tool_calls"])
        msg.content = [{"type": "text", "text": "hi"}]
        msg.tool_calls = None
        s = _summarize_message(msg)
        assert s["content_len"] == -1

    def test_tool_call_missing_name(self):
        msg = MagicMock(spec=["content", "tool_calls"])
        msg.content = ""
        msg.tool_calls = [{"args": {}}]
        s = _summarize_message(msg)
        assert s["tool_calls"] == ["?"]

    def test_includes_finish_metadata_when_present(self):
        msg = MagicMock(spec=["content", "tool_calls", "response_metadata"])
        msg.content = ""
        msg.tool_calls = None
        msg.response_metadata = {"finish_reason": "SAFETY", "is_blocked": True}
        s = _summarize_message(msg)
        assert s["finish"]["finish_reason"] == "SAFETY"
        assert s["finish"]["is_blocked"] is True

    def test_omits_finish_field_when_no_metadata(self):
        msg = MagicMock(spec=["content", "tool_calls"])
        msg.content = "ok"
        msg.tool_calls = None
        s = _summarize_message(msg)
        assert "finish" not in s


class TestExtractFinishDiagnostics:
    """Tests for the LangChain-generic finish-reason / safety extractor."""

    def test_vertex_style_metadata(self):
        msg = MagicMock(spec=["response_metadata", "usage_metadata"])
        msg.response_metadata = {
            "finish_reason": "SAFETY",
            "is_blocked": True,
            "safety_ratings": [
                {"category": "HARM_CATEGORY_HATE", "probability": "HIGH"}
            ],
        }
        msg.usage_metadata = {
            "input_tokens": 100,
            "output_tokens": 0,
            "total_tokens": 100,
        }
        diag = _extract_finish_diagnostics(msg)
        assert diag["finish_reason"] == "SAFETY"
        assert diag["is_blocked"] is True
        assert diag["safety_ratings"][0]["probability"] == "HIGH"
        assert diag["usage"] == {
            "input_tokens": 100,
            "output_tokens": 0,
            "total_tokens": 100,
        }

    def test_anthropic_style_stop_reason(self):
        """Anthropic uses ``stop_reason`` rather than ``finish_reason``."""
        msg = MagicMock(spec=["response_metadata", "usage_metadata"])
        msg.response_metadata = {"stop_reason": "max_tokens"}
        msg.usage_metadata = {"input_tokens": 50, "output_tokens": 4096}
        diag = _extract_finish_diagnostics(msg)
        assert diag["stop_reason"] == "max_tokens"
        assert "finish_reason" not in diag
        assert diag["usage"]["output_tokens"] == 4096

    def test_openai_style_finish_reason(self):
        msg = MagicMock(spec=["response_metadata", "usage_metadata"])
        msg.response_metadata = {"finish_reason": "content_filter"}
        msg.usage_metadata = None
        diag = _extract_finish_diagnostics(msg)
        assert diag == {"finish_reason": "content_filter"}

    def test_no_metadata_returns_empty(self):
        msg = MagicMock(spec=[])  # no response_metadata, no usage_metadata
        assert _extract_finish_diagnostics(msg) == {}

    def test_skips_empty_values(self):
        msg = MagicMock(spec=["response_metadata", "usage_metadata"])
        msg.response_metadata = {
            "finish_reason": "STOP",
            "safety_ratings": [],
            "prompt_feedback": {},
            "is_blocked": None,
        }
        msg.usage_metadata = {}
        diag = _extract_finish_diagnostics(msg)
        assert diag == {"finish_reason": "STOP"}

    def test_non_dict_response_metadata_safe(self):
        msg = MagicMock(spec=["response_metadata", "usage_metadata"])
        msg.response_metadata = "unexpected string"
        msg.usage_metadata = None
        assert _extract_finish_diagnostics(msg) == {}


class TestIsGeminiMessage:
    """Tests for the Vertex/Gemini provider-detection helper."""

    def test_vertex_safety_ratings_marker(self):
        msg = MagicMock(spec=["response_metadata"])
        msg.response_metadata = {"safety_ratings": [], "finish_reason": "STOP"}
        assert _is_gemini_message(msg) is True

    def test_vertex_is_blocked_marker(self):
        msg = MagicMock(spec=["response_metadata"])
        msg.response_metadata = {"is_blocked": False}
        assert _is_gemini_message(msg) is True

    def test_vertex_prompt_feedback_marker(self):
        msg = MagicMock(spec=["response_metadata"])
        msg.response_metadata = {"prompt_feedback": {}}
        assert _is_gemini_message(msg) is True

    def test_openai_metadata_not_detected(self):
        msg = MagicMock(spec=["response_metadata"])
        msg.response_metadata = {
            "model_name": "gpt-4o",
            "finish_reason": "stop",
            "system_fingerprint": "fp_abc",
        }
        assert _is_gemini_message(msg) is False

    def test_anthropic_metadata_not_detected(self):
        msg = MagicMock(spec=["response_metadata"])
        msg.response_metadata = {
            "model_name": "claude-sonnet-4",
            "stop_reason": "end_turn",
        }
        assert _is_gemini_message(msg) is False

    def test_missing_response_metadata(self):
        msg = MagicMock(spec=[])
        assert _is_gemini_message(msg) is False

    def test_non_dict_response_metadata(self):
        msg = MagicMock(spec=["response_metadata"])
        msg.response_metadata = "weird"
        assert _is_gemini_message(msg) is False


def _make_msg(content="", tool_calls=None, response_metadata=None):
    """Build a minimal AIMessage stand-in for _process_agent_output tests."""
    msg = MagicMock(spec=["content", "tool_calls", "response_metadata"])
    msg.content = content
    msg.tool_calls = tool_calls
    msg.response_metadata = response_metadata
    return msg


class TestProcessAgentOutputGeminiCarveOut:
    """Tests for the Gemini-only behavior of _process_agent_output.

    Gemini emits final synthesis text alongside a write_todos tool call;
    other providers always separate them. We must pick up content for
    Gemini messages with tool calls but NOT for OpenAI/Anthropic ones.
    """

    _GEMINI_META = {"safety_ratings": [], "is_blocked": False, "finish_reason": "STOP"}
    _OPENAI_META = {"model_name": "gpt-4o", "finish_reason": "stop"}

    def test_gemini_message_with_content_and_write_todos_picked_up(self):
        msg = _make_msg(
            content="Final synthesis answer here.",
            tool_calls=[{"name": "write_todos", "args": {}}],
            response_metadata=self._GEMINI_META,
        )
        result = _process_agent_output({"messages": [msg]})
        assert result["response_text"] == "Final synthesis answer here."

    def test_openai_message_with_content_and_tool_call_skipped(self):
        msg = _make_msg(
            content="Let me think first",
            tool_calls=[{"name": "write_todos", "args": {}}],
            response_metadata=self._OPENAI_META,
        )
        result = _process_agent_output({"messages": [msg]})
        assert result["response_text"] == ""

    def test_gemini_message_empty_content_with_tool_call_no_overwrite(self):
        msg = _make_msg(
            content="",
            tool_calls=[{"name": "write_todos", "args": {}}],
            response_metadata=self._GEMINI_META,
        )
        result = _process_agent_output({"messages": [msg]})
        assert result["response_text"] == ""

    def test_search_message_still_extracted_as_query(self):
        msg = _make_msg(
            content="anything",
            tool_calls=[{"name": "search_documents", "args": {"query": "food"}}],
            response_metadata=self._GEMINI_META,
        )
        result = _process_agent_output({"messages": [msg]})
        assert result["tool_queries"] == ["food"]
        assert result["response_text"] == ""

    def test_task_delegation_still_extracted(self):
        msg = _make_msg(
            content="anything",
            tool_calls=[{"name": "task", "args": {"description": "research X"}}],
            response_metadata=self._GEMINI_META,
        )
        result = _process_agent_output({"messages": [msg]})
        assert result["task_delegations"] == ["research X"]
        assert result["response_text"] == ""

    def test_plain_final_message_still_picked_up(self):
        msg = _make_msg(
            content="answer",
            tool_calls=None,
            response_metadata=None,
        )
        result = _process_agent_output({"messages": [msg]})
        assert result["response_text"] == "answer"

    def test_later_synthesis_message_overwrites_earlier(self):
        early = _make_msg(
            content="intermediate",
            tool_calls=[{"name": "write_todos", "args": {}}],
            response_metadata=self._GEMINI_META,
        )
        final = _make_msg(
            content="FINAL",
            tool_calls=[{"name": "write_todos", "args": {}}],
            response_metadata=self._GEMINI_META,
        )
        result = _process_agent_output({"messages": [early, final]})
        assert result["response_text"] == "FINAL"


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


class TestNextCitationIndex:
    """Tests for _next_citation_index — the index a new search result will get."""

    def test_empty_or_none_starts_at_1(self):
        assert _next_citation_index(None) == 1
        assert _next_citation_index([]) == 1

    def test_returns_one_more_than_max(self):
        prior = [
            {"index": 1},
            {"index": 5},
            {"index": 3},
        ]
        assert _next_citation_index(prior) == 6

    def test_ignores_non_int_indices(self):
        prior = [
            {"index": "not an int"},
            {"index": None},
            {"index": 7},
        ]
        assert _next_citation_index(prior) == 8

    def test_all_non_int_falls_back_to_1(self):
        assert _next_citation_index([{"index": None}, {"index": "x"}]) == 1


class TestExtractPriorSources:
    """Tests for _extract_prior_sources — pulling sources from history."""

    def test_returns_empty_for_none_or_empty(self):
        assert _extract_prior_sources(None) == []
        assert _extract_prior_sources([]) == []

    def test_extracts_sources_from_assistant_messages_only(self):
        history = [
            {"role": "user", "content": "Q1", "sources": [{"index": 99}]},
            {
                "role": "assistant",
                "content": "A1",
                "sources": [{"index": 1, "title": "T"}],
            },
        ]
        result = _extract_prior_sources(history)
        assert [s["index"] for s in result] == [1]

    def test_dedupes_across_turns_by_index(self):
        """A citation re-cited in turn 2 must appear only once."""
        history = [
            {
                "role": "assistant",
                "content": "A1",
                "sources": [
                    {"index": 1, "title": "T1"},
                    {"index": 2, "title": "T2"},
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
                    },  # duplicate index — latest wins
                    {"index": 3, "title": "T3"},
                ],
            },
        ]
        result = _extract_prior_sources(history)
        assert [s["index"] for s in result] == [1, 2, 3]
        # Last-write-wins lets the most recent message refine an entry if needed.
        assert result[1]["title"] == "T2 (latest)"

    def test_ignores_assistant_messages_without_sources(self):
        history = [
            {"role": "assistant", "content": "A1"},  # no sources key at all
            {"role": "assistant", "content": "A2", "sources": []},  # empty list
            {"role": "assistant", "content": "A3", "sources": None},  # explicit None
        ]
        assert _extract_prior_sources(history) == []

    def test_ignores_sources_with_non_int_index(self):
        history = [
            {
                "role": "assistant",
                "content": "A1",
                "sources": [
                    {"index": "abc", "title": "Bad"},
                    {"index": 2, "title": "Good"},
                ],
            },
        ]
        result = _extract_prior_sources(history)
        assert [s["index"] for s in result] == [2]


class TestLoadSystemPromptPriorSources:
    """Tests for _load_system_prompt's prior-sources block."""

    def test_no_prior_sources_omits_block(self):
        prompt = _load_system_prompt(data_source="wfp")
        assert "Previously cited sources" not in prompt

    def test_with_prior_sources_includes_block_and_titles(self):
        prior = [
            {"index": 1, "title": "Eval of Climate Policies"},
            {"index": 2, "title": "Resilience Programme Report"},
        ]
        prompt = _load_system_prompt(data_source="wfp", prior_sources=prior)
        assert "Previously cited sources" in prompt
        assert "[1] Eval of Climate Policies" in prompt
        assert "[2] Resilience Programme Report" in prompt

    def test_with_prior_sources_advertises_next_index(self):
        prior = [{"index": 7, "title": "T"}]
        prompt = _load_system_prompt(data_source="wfp", prior_sources=prior)
        # New search results should be numbered starting from [8].
        assert "[8]" in prompt
