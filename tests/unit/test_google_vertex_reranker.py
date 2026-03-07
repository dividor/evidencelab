"""Unit tests for Google Vertex AI reranker (Discovery Engine)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ui.backend.services.google_vertex_reranker import rerank_with_google_vertex


def _make_fake_record(record_id: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(id=record_id, score=score)


@patch("ui.backend.services.google_vertex_reranker._load_gcp_project_id")
@patch("ui.backend.services.google_vertex_reranker.discoveryengine")
def test_rerank_returns_scores_in_original_order(mock_de, mock_project):
    mock_project.return_value = "test-project"

    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = (
        "projects/test-project/locations/global/rankingConfigs/default_ranking_config"
    )

    # API returns docs reordered: doc2 first, then doc0, then doc1
    mock_response = SimpleNamespace(
        records=[
            _make_fake_record("2", 0.95),
            _make_fake_record("0", 0.80),
            _make_fake_record("1", 0.60),
        ]
    )
    mock_client.rank.return_value = mock_response

    scores = rerank_with_google_vertex(
        query="test query",
        documents=["doc A", "doc B", "doc C"],
        model_id="semantic-ranker-default@latest",
    )

    assert len(scores) == 3
    # Scores should be mapped back to original positions
    assert scores[0] == 0.80  # doc0
    assert scores[1] == 0.60  # doc1
    assert scores[2] == 0.95  # doc2


@patch("ui.backend.services.google_vertex_reranker._load_gcp_project_id")
@patch("ui.backend.services.google_vertex_reranker.discoveryengine")
def test_rerank_builds_correct_request(mock_de, mock_project):
    mock_project.return_value = "my-project"

    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config-path"
    mock_client.rank.return_value = SimpleNamespace(
        records=[
            _make_fake_record("0", 0.5),
            _make_fake_record("1", 0.3),
        ]
    )

    rerank_with_google_vertex(
        query="climate change",
        documents=["doc one", "doc two"],
        model_id="semantic-ranker-fast-004",
    )

    # Verify RankingRecord creation
    mock_de.RankingRecord.assert_any_call(id="0", content="doc one")
    mock_de.RankingRecord.assert_any_call(id="1", content="doc two")

    # Verify RankRequest creation
    call_kwargs = mock_de.RankRequest.call_args
    assert call_kwargs[1]["model"] == "semantic-ranker-fast-004"
    assert call_kwargs[1]["query"] == "climate change"
    assert call_kwargs[1]["top_n"] == 2


@patch("ui.backend.services.google_vertex_reranker._load_gcp_project_id")
@patch("ui.backend.services.google_vertex_reranker.discoveryengine")
def test_rerank_missing_doc_gets_zero_score(mock_de, mock_project):
    mock_project.return_value = "p"

    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"

    # API only returns one of two docs (missing doc index 1)
    mock_client.rank.return_value = SimpleNamespace(
        records=[_make_fake_record("0", 0.9)]
    )

    scores = rerank_with_google_vertex("q", ["a", "b"], "model")
    assert scores == [0.9, 0.0]
