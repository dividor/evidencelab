"""Unit tests for the LangGraph research assistant graph."""

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

# Mock the heavy imports that assistant_graph pulls in transitively.
# assistant_tools -> search -> search_models -> google_vertex_reranker -> google.cloud
# We mock assistant_tools at the module level before importing the graph.
_mock_tools = ModuleType("ui.backend.services.assistant_tools")
_mock_search_fn = MagicMock(return_value=[])
_mock_tools.search_documents = _mock_search_fn
sys.modules.setdefault("ui.backend.services.assistant_tools", _mock_tools)

from ui.backend.services.assistant_graph import (  # noqa: E402
    ResearchState,
    _get_conversation_context,
    build_research_graph,
    plan_node,
    reflect_node,
    search_node,
    should_continue,
    synthesize_node,
)


def _make_state(**overrides) -> ResearchState:
    """Create a default ResearchState with overrides."""
    defaults: ResearchState = {
        "messages": [HumanMessage(content="test query")],
        "query": "test query",
        "search_queries": [],
        "search_results": [],
        "synthesis": "",
        "reflection": "",
        "iteration": 0,
        "max_iterations": 3,
        "sources": [],
        "should_continue": True,
        "data_source": None,
    }
    defaults.update(overrides)
    return defaults


class TestGetConversationContext:
    """Tests for _get_conversation_context helper."""

    def test_empty_messages(self):
        result = _get_conversation_context([])
        assert result == ""

    def test_single_user_message(self):
        msgs = [HumanMessage(content="Hello")]
        result = _get_conversation_context(msgs)
        assert "User: Hello" in result

    def test_mixed_messages(self):
        msgs = [
            HumanMessage(content="Question"),
            AIMessage(content="Answer"),
        ]
        result = _get_conversation_context(msgs)
        assert "User: Question" in result
        assert "Assistant: Answer" in result

    def test_truncates_long_content(self):
        long_text = "x" * 500
        msgs = [HumanMessage(content=long_text)]
        result = _get_conversation_context(msgs)
        assert "..." in result
        assert len(result) < 500

    def test_respects_max_msgs(self):
        msgs = [HumanMessage(content=f"Msg {i}") for i in range(10)]
        result = _get_conversation_context(msgs, max_msgs=3)
        # Should only include the last 3
        assert "Msg 7" in result
        assert "Msg 8" in result
        assert "Msg 9" in result
        assert "Msg 0" not in result


class TestPlanNode:
    """Tests for the plan_node function."""

    def test_decomposes_into_queries(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(
            content='["food security impact", "nutrition outcomes"]'
        )

        state = _make_state(query="What are the impacts on food security?")
        result = plan_node(state, llm)

        assert "search_queries" in result
        assert len(result["search_queries"]) == 2
        assert "food security impact" in result["search_queries"]

    def test_handles_markdown_code_fences(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(
            content='```json\n["query 1", "query 2"]\n```'
        )

        state = _make_state(query="test")
        result = plan_node(state, llm)

        assert len(result["search_queries"]) == 2

    def test_fallback_on_invalid_json(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="not valid json")

        state = _make_state(query="my question")
        result = plan_node(state, llm)

        # Should fall back to the original query
        assert result["search_queries"] == ["my question"]

    def test_fallback_on_non_list_json(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content='{"queries": ["a", "b"]}')

        state = _make_state(query="my question")
        result = plan_node(state, llm)

        # Parsed a dict instead of list, falls back
        assert result["search_queries"] == ["my question"]

    def test_limits_to_3_queries(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content='["q1", "q2", "q3", "q4", "q5"]')

        state = _make_state(query="test")
        result = plan_node(state, llm)

        assert len(result["search_queries"]) == 3


class TestSearchNode:
    """Tests for the search_node function."""

    def test_searches_and_returns_results(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            {
                "chunk_id": "c1",
                "doc_id": "d1",
                "title": "Doc 1",
                "text": "Content",
                "score": 0.9,
            },
            {
                "chunk_id": "c2",
                "doc_id": "d2",
                "title": "Doc 2",
                "text": "Content",
                "score": 0.8,
            },
        ]

        state = _make_state(search_queries=["food security"])
        result = search_node(state)

        assert "search_results" in result
        assert len(result["search_results"]) == 2
        _mock_search_fn.assert_called_once_with(
            query="food security",
            data_source=None,
            limit=20,
        )

    def test_deduplicates_by_chunk_id(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            {
                "chunk_id": "c1",
                "doc_id": "d1",
                "title": "Doc",
                "text": "T",
                "score": 0.9,
            },
        ]

        # State already has c1 in search_results
        state = _make_state(
            search_queries=["query"],
            search_results=[
                {
                    "chunk_id": "c1",
                    "doc_id": "d1",
                    "title": "Doc",
                    "text": "T",
                    "score": 0.8,
                },
            ],
        )
        result = search_node(state)

        # c1 should appear only once (the existing one)
        chunk_ids = [r["chunk_id"] for r in result["search_results"]]
        assert chunk_ids.count("c1") == 1

    def test_sorts_by_score_descending(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            {"chunk_id": "c2", "doc_id": "d2", "text": "T", "score": 0.5},
            {"chunk_id": "c3", "doc_id": "d3", "text": "T", "score": 0.9},
        ]

        state = _make_state(
            search_queries=["q"],
            search_results=[
                {"chunk_id": "c1", "doc_id": "d1", "text": "T", "score": 0.7},
            ],
        )
        result = search_node(state)

        scores = [r["score"] for r in result["search_results"]]
        assert scores == sorted(scores, reverse=True)

    def test_multiple_queries(self):
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = [
            [{"chunk_id": "c1", "doc_id": "d1", "text": "T", "score": 0.9}],
            [{"chunk_id": "c2", "doc_id": "d2", "text": "T", "score": 0.8}],
        ]

        state = _make_state(search_queries=["query 1", "query 2"])
        result = search_node(state)

        assert len(result["search_results"]) == 2
        assert _mock_search_fn.call_count == 2


class TestSynthesizeNode:
    """Tests for the synthesize_node function."""

    def test_produces_synthesis_and_sources(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(
            content="Food security impacts are significant [1]."
        )

        state = _make_state(
            query="food security",
            search_results=[
                {
                    "chunk_id": "c1",
                    "doc_id": "d1",
                    "title": "Report A",
                    "text": "Detailed content about food security.",
                    "score": 0.9,
                    "page": 5,
                },
                {
                    "chunk_id": "c2",
                    "doc_id": "d2",
                    "title": "Report B",
                    "text": "More data on nutrition.",
                    "score": 0.8,
                    "page": 10,
                },
            ],
        )
        result = synthesize_node(state, llm)

        assert "synthesis" in result
        assert "sources" in result
        assert len(result["sources"]) == 2
        assert result["sources"][0]["docId"] == "d1"
        assert result["sources"][0]["title"] == "Report A"

    def test_deduplicates_sources_by_doc_id(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="Answer")

        state = _make_state(
            search_results=[
                {
                    "chunk_id": "c1",
                    "doc_id": "d1",
                    "title": "Doc",
                    "text": "T1",
                    "score": 0.9,
                },
                {
                    "chunk_id": "c2",
                    "doc_id": "d1",
                    "title": "Doc",
                    "text": "T2",
                    "score": 0.8,
                },
            ],
        )
        result = synthesize_node(state, llm)

        # Same doc_id should appear only once
        assert len(result["sources"]) == 1

    def test_truncates_long_text_in_sources(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="Answer")

        long_text = "x" * 300
        state = _make_state(
            search_results=[
                {
                    "chunk_id": "c1",
                    "doc_id": "d1",
                    "title": "Doc",
                    "text": long_text,
                    "score": 0.9,
                },
            ],
        )
        result = synthesize_node(state, llm)

        source_text = result["sources"][0]["text"]
        assert len(source_text) < 300
        assert source_text.endswith("...")


class TestReflectNode:
    """Tests for the reflect_node function."""

    def test_decides_to_stop(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(
            content=json.dumps(
                {
                    "should_continue": False,
                    "reasoning": "Answer is comprehensive.",
                    "additional_queries": [],
                }
            )
        )

        state = _make_state(iteration=0, max_iterations=3, synthesis="Answer")
        result = reflect_node(state, llm)

        assert result["should_continue"] is False
        assert result["iteration"] == 1

    def test_decides_to_continue(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(
            content=json.dumps(
                {
                    "should_continue": True,
                    "reasoning": "Missing details on nutrition.",
                    "additional_queries": ["nutrition outcomes"],
                }
            )
        )

        state = _make_state(iteration=0, max_iterations=3, synthesis="Partial")
        result = reflect_node(state, llm)

        assert result["should_continue"] is True
        assert result["search_queries"] == ["nutrition outcomes"]

    def test_stops_at_max_iterations(self):
        llm = MagicMock()
        # LLM should NOT be called when max iterations reached
        state = _make_state(iteration=2, max_iterations=3, synthesis="Answer")
        result = reflect_node(state, llm)

        assert result["should_continue"] is False
        assert result["iteration"] == 3
        llm.invoke.assert_not_called()

    def test_handles_invalid_json(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="not json at all")

        state = _make_state(iteration=0, max_iterations=3, synthesis="Answer")
        result = reflect_node(state, llm)

        # Should default to not continuing
        assert result["should_continue"] is False

    def test_handles_markdown_code_fences(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(
            content='```json\n{"should_continue": false, "reasoning": "Good"}\n```'
        )

        state = _make_state(iteration=0, max_iterations=3, synthesis="Answer")
        result = reflect_node(state, llm)

        assert result["should_continue"] is False

    def test_limits_additional_queries_to_2(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(
            content=json.dumps(
                {
                    "should_continue": True,
                    "reasoning": "Need more info",
                    "additional_queries": ["q1", "q2", "q3", "q4"],
                }
            )
        )

        state = _make_state(iteration=0, max_iterations=3, synthesis="Partial")
        result = reflect_node(state, llm)

        assert len(result["search_queries"]) <= 2


class TestShouldContinue:
    """Tests for the should_continue routing function."""

    def test_returns_search_when_true(self):
        state = _make_state(should_continue=True)
        assert should_continue(state) == "search"

    def test_returns_end_when_false(self):
        state = _make_state(should_continue=False)
        result = should_continue(state)
        assert result == "__end__"

    def test_defaults_to_end(self):
        # should_continue not set at all
        state: ResearchState = {
            "messages": [],
            "query": "",
            "search_queries": [],
            "search_results": [],
            "synthesis": "",
            "reflection": "",
            "iteration": 0,
            "max_iterations": 3,
            "sources": [],
            "should_continue": False,
            "data_source": None,
        }
        result = should_continue(state)
        assert result == "__end__"


class TestBuildResearchGraph:
    """Tests for the build_research_graph function."""

    def test_builds_graph_successfully(self):
        llm = MagicMock()
        graph = build_research_graph(llm)
        # The compiled graph should have an invoke method
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "stream")

    def test_full_graph_e2e(self):
        """End-to-end test with mocked LLM and search."""
        _mock_search_fn.reset_mock()
        _mock_search_fn.side_effect = None
        _mock_search_fn.return_value = [
            {
                "chunk_id": "c1",
                "doc_id": "d1",
                "title": "Test Doc",
                "text": "Content about food security.",
                "score": 0.9,
            },
        ]

        llm = MagicMock()
        # Plan: return queries
        # Synthesize: return answer
        # Reflect: stop
        call_count = [0]

        def mock_invoke(messages):
            call_count[0] += 1
            if call_count[0] == 1:
                # Plan
                return AIMessage(content='["food security impacts"]')
            elif call_count[0] == 2:
                # Synthesize
                return AIMessage(content="Food security is important [1].")
            else:
                # Reflect
                return AIMessage(
                    content=json.dumps(
                        {
                            "should_continue": False,
                            "reasoning": "Answer is good.",
                        }
                    )
                )

        llm.invoke.side_effect = mock_invoke

        graph = build_research_graph(llm)

        initial_state: ResearchState = {
            "messages": [HumanMessage(content="food security")],
            "query": "food security",
            "search_queries": [],
            "search_results": [],
            "synthesis": "",
            "reflection": "",
            "iteration": 0,
            "max_iterations": 3,
            "sources": [],
            "should_continue": True,
            "data_source": None,
        }

        result = graph.invoke(initial_state)

        assert result["synthesis"] != ""
        assert len(result["sources"]) >= 1
        assert result["should_continue"] is False
