"""Unit tests for Azure Foundry reranker (extracted module)."""

import json

import pytest

from ui.backend.services.azure_foundry_reranker import (
    _get_azure_foundry_api_key,
    _get_azure_foundry_rerank_endpoint,
    _scores_from_data,
    _scores_from_list,
    _scores_from_results,
    parse_azure_rerank_response,
)

# --- _scores_from_results ---


def test_scores_from_results_indexed():
    results = [
        {"index": 1, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.5},
    ]
    scores = _scores_from_results(results, 2)
    assert scores == [0.5, 0.9]


def test_scores_from_results_unindexed():
    results = [{"score": 0.8}, {"score": 0.6}]
    scores = _scores_from_results(results, 2)
    assert scores == [0.8, 0.6]


def test_scores_from_results_empty():
    assert _scores_from_results([], 2) is None


def test_scores_from_results_none():
    assert _scores_from_results(None, 2) is None


# --- _scores_from_list ---


def test_scores_from_list_valid():
    assert _scores_from_list([0.5, 0.9, 0.1]) == [0.5, 0.9, 0.1]


def test_scores_from_list_with_ints():
    assert _scores_from_list([1, 2, 3]) == [1.0, 2.0, 3.0]


def test_scores_from_list_invalid():
    assert _scores_from_list("not a list") is None


def test_scores_from_list_invalid_items():
    assert _scores_from_list([0.5, "bad"]) is None


# --- _scores_from_data ---


def test_scores_from_data_with_results_key():
    data = {"results": [{"index": 0, "relevance_score": 0.7}]}
    scores = _scores_from_data(data, 1)
    assert scores == [0.7]


def test_scores_from_data_with_scores_key():
    data = {"scores": [0.5, 0.8]}
    scores = _scores_from_data(data, 2)
    assert scores == [0.5, 0.8]


def test_scores_from_data_non_dict():
    assert _scores_from_data("not a dict", 2) is None


# --- parse_azure_rerank_response ---


def test_parse_response_from_string():
    response = json.dumps({"results": [{"index": 0, "relevance_score": 0.9}]})
    scores = parse_azure_rerank_response(response, 1)
    assert scores == [0.9]


def test_parse_response_from_dict():
    response = {"results": [{"index": 0, "relevance_score": 0.5}]}
    scores = parse_azure_rerank_response(response, 1)
    assert scores == [0.5]


def test_parse_response_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_azure_rerank_response("not json", 1)


def test_parse_response_missing_scores():
    with pytest.raises(ValueError, match="missing scores"):
        parse_azure_rerank_response({"other": "data"}, 1)


# --- _get_azure_foundry_api_key ---


def test_get_api_key_from_env(monkeypatch):
    monkeypatch.setenv("AZURE_FOUNDRY_KEY", "test-key")
    assert _get_azure_foundry_api_key() == "test-key"


def test_get_api_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("AZURE_FOUNDRY_KEY", raising=False)
    with pytest.raises(ValueError, match="AZURE_FOUNDRY_KEY"):
        _get_azure_foundry_api_key()


# --- _get_azure_foundry_rerank_endpoint ---


def test_endpoint_from_config():
    config = {"endpoint_url": "https://my-resource.services.ai.azure.com"}
    endpoint = _get_azure_foundry_rerank_endpoint(config, "model")
    assert endpoint == (
        "https://my-resource.services.ai.azure.com/providers/cohere/v2/rerank"
    )


def test_endpoint_passthrough_cohere_url():
    config = {
        "endpoint_url": "https://my-resource.services.ai.azure.com/providers/cohere/v2/rerank"
    }
    endpoint = _get_azure_foundry_rerank_endpoint(config, "model")
    assert endpoint == (
        "https://my-resource.services.ai.azure.com/providers/cohere/v2/rerank"
    )


def test_endpoint_raises_when_missing(monkeypatch):
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        _get_azure_foundry_rerank_endpoint({}, "model")
