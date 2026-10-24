"""Unit tests for Google Vertex AI reranker (Discovery Engine)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google.api_core import exceptions as gax_exceptions

from ui.backend.services.google_vertex_reranker import (
    DEFAULT_VERTEX_RERANK_BATCH_SIZE,
    RerankerUnavailableError,
    _load_batch_size,
    rerank_with_google_vertex,
)


def _make_fake_record(record_id: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(id=record_id, score=score)


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
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


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
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


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
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


# ---------------------------------------------------------------------------
# Transient-failure fallback: known-recoverable Google errors get repackaged
# as RerankerUnavailableError so the search pipeline can fall back to the
# unranked results instead of bubbling a 500 to the user.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transient_exc",
    [
        gax_exceptions.ServiceUnavailable("503 The service is currently unavailable."),
        gax_exceptions.DeadlineExceeded("504 Deadline exceeded."),
        gax_exceptions.GatewayTimeout("504 Gateway timeout."),
        gax_exceptions.InternalServerError("500 Internal."),
    ],
)
@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_raises_unavailable_on_known_transient_errors(
    mock_de, mock_project, transient_exc
):
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"
    mock_client.rank.side_effect = transient_exc

    with pytest.raises(RerankerUnavailableError) as excinfo:
        rerank_with_google_vertex("q", ["a", "b"], "model")

    # The original Google error must be preserved as the cause so SREs can
    # still see exactly which transient code fired.
    assert excinfo.value.__cause__ is transient_exc
    # And the message should name the kind of failure for log grep-ability.
    assert type(transient_exc).__name__ in str(excinfo.value)


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_does_not_swallow_real_bugs(mock_de, mock_project):
    """A non-transient error must still propagate — silently ignoring it
    would mask a real reranker bug behind the fallback."""
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"
    mock_client.rank.side_effect = ValueError("malformed request")

    with pytest.raises(ValueError, match="malformed request"):
        rerank_with_google_vertex("q", ["a", "b"], "model")


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_permission_denied_propagates(mock_de, mock_project):
    """Auth/permission errors are not transient — they must surface so an
    operator notices the credential issue rather than seeing silent
    no-rerank fallback forever."""
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"
    mock_client.rank.side_effect = gax_exceptions.PermissionDenied("403 nope")

    with pytest.raises(gax_exceptions.PermissionDenied):
        rerank_with_google_vertex("q", ["a", "b"], "model")


# ---------------------------------------------------------------------------
# Batching: a search can hand the reranker thousands of chunks (a heatmapper
# cell sends up to 1000 documents, 5000 chunks with wide search), and the
# Ranking API takes at most 1000 records in one request. Documents are scored
# in slices and the scores come back in document order.
# ---------------------------------------------------------------------------


def _install_echo_rank(mock_de, mock_client):
    """Make the mocked API score each record by its id, so batches are
    distinguishable and the reassembled order can be checked."""
    mock_de.RankingRecord.side_effect = lambda id, content: SimpleNamespace(
        id=id, content=content
    )
    mock_de.RankRequest.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
    mock_client.rank.side_effect = lambda request: SimpleNamespace(
        records=[
            SimpleNamespace(id=record.id, score=int(record.id) / 10)
            for record in request.records
        ]
    )


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_scores_in_batches_and_keeps_document_order(mock_de, mock_project):
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"
    _install_echo_rank(mock_de, mock_client)

    scores = rerank_with_google_vertex(
        "q", ["d0", "d1", "d2", "d3", "d4"], "model", batch_size=2
    )

    assert scores == [0.0, 0.1, 0.2, 0.3, 0.4]
    requests = [call.kwargs["request"] for call in mock_client.rank.call_args_list]
    assert [len(request.records) for request in requests] == [2, 2, 1]
    assert [[r.id for r in request.records] for request in requests] == [
        ["0", "1"],
        ["2", "3"],
        ["4"],
    ]
    # Every request asks for all of its own records back.
    assert [request.top_n for request in requests] == [2, 2, 1]
    assert all(request.query == "q" for request in requests)


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_uses_one_request_when_within_batch_size(mock_de, mock_project):
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"
    _install_echo_rank(mock_de, mock_client)

    scores = rerank_with_google_vertex("q", ["d0", "d1", "d2"], "model", batch_size=200)

    assert scores == [0.0, 0.1, 0.2]
    assert mock_client.rank.call_count == 1


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_never_sends_empty_documents(mock_de, mock_project):
    """The API rejects a record with empty content (INVALID_ARGUMENT), and a
    chunk without text has nothing to rank anyway: it scores 0.0 and is left
    out of the request."""
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"
    _install_echo_rank(mock_de, mock_client)

    scores = rerank_with_google_vertex("q", ["d0", "", "d2"], "model")

    assert scores == [0.0, 0.0, 0.2]
    (request,) = [call.kwargs["request"] for call in mock_client.rank.call_args_list]
    assert [r.id for r in request.records] == ["0", "2"]


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_all_empty_documents_makes_no_request(mock_de, mock_project):
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"

    assert rerank_with_google_vertex("q", ["", ""], "model") == [0.0, 0.0]
    mock_client.rank.assert_not_called()


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_transient_error_in_later_batch_raises_unavailable(
    mock_de, mock_project
):
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"
    outage = gax_exceptions.ServiceUnavailable("503 unavailable")
    mock_client.rank.side_effect = [
        SimpleNamespace(records=[_make_fake_record("0", 0.9)]),
        outage,
    ]

    with pytest.raises(RerankerUnavailableError) as excinfo:
        rerank_with_google_vertex("q", ["a", "b"], "model", batch_size=1)

    assert excinfo.value.__cause__ is outage


@patch("pipeline.utilities.google_vertex_client._load_gcp_project_id")
@patch("google.cloud.discoveryengine_v1", create=True)
def test_rerank_invalid_argument_propagates_with_batch_logged(
    mock_de, mock_project, caplog
):
    """A rejected request is a bug in what we sent. It must surface, and the
    log must say how big the batch was so the next person can size it."""
    mock_project.return_value = "p"
    mock_client = MagicMock()
    mock_de.RankServiceClient.return_value = mock_client
    mock_client.ranking_config_path.return_value = "config"
    mock_client.rank.side_effect = gax_exceptions.InvalidArgument("400 too big")

    caplog.set_level("ERROR")
    with pytest.raises(gax_exceptions.InvalidArgument):
        rerank_with_google_vertex("q", ["abc", "de"], "model")

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "rejected a batch of 2 records" in messages
    assert "5 characters" in messages


def test_rerank_rejects_non_positive_batch_size():
    with pytest.raises(ValueError, match="batch_size must be at least 1"):
        rerank_with_google_vertex("q", ["a"], "model", batch_size=0)


# ---------------------------------------------------------------------------
# VERTEX_RERANK_BATCH_SIZE: unset means the default; a value that is set but
# unusable stops the API rather than reranking with a size nobody chose.
# ---------------------------------------------------------------------------


def test_batch_size_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("VERTEX_RERANK_BATCH_SIZE", raising=False)
    assert _load_batch_size() == DEFAULT_VERTEX_RERANK_BATCH_SIZE


def test_batch_size_reads_environment(monkeypatch):
    monkeypatch.setenv("VERTEX_RERANK_BATCH_SIZE", "50")
    assert _load_batch_size() == 50


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5", "1001"])
def test_batch_size_rejects_unusable_values(monkeypatch, raw):
    monkeypatch.setenv("VERTEX_RERANK_BATCH_SIZE", raw)
    with pytest.raises(ValueError, match="VERTEX_RERANK_BATCH_SIZE"):
        _load_batch_size()
