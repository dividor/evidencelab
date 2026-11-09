"""Tests for the Cohere-compatible reranker provider."""

import io
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from ui.backend.services import cohere_compatible_reranker as mod
from ui.backend.services.google_vertex_reranker import RerankerUnavailableError

MODULE = "ui.backend.services.cohere_compatible_reranker"


def _response(payload):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    return resp


def _http_error(code, body="boom"):
    return HTTPError("https://x", code, "err", {}, io.BytesIO(body.encode()))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("COHERE_BASE_URL", "https://api.example.com/v2")
    monkeypatch.setenv("COHERE_API_KEY", "secret")


class TestEndpoint:
    def test_appends_rerank(self):
        assert mod._get_endpoint({}) == "https://api.example.com/v2/rerank"

    def test_does_not_duplicate_rerank_or_slash(self, monkeypatch):
        monkeypatch.setenv("COHERE_BASE_URL", "https://api.example.com/v2/rerank/")
        assert mod._get_endpoint({}) == "https://api.example.com/v2/rerank"

    def test_config_endpoint_wins(self):
        cfg = {"endpoint_url": "https://other.example.com/r"}
        assert mod._get_endpoint(cfg) == "https://other.example.com/r/rerank"

    def test_custom_env_name(self, monkeypatch):
        monkeypatch.setenv("MY_URL", "https://custom.example.com")
        assert mod._get_endpoint({"base_url_env": "MY_URL"}).startswith(
            "https://custom.example.com"
        )

    def test_missing_endpoint_raises(self, monkeypatch):
        monkeypatch.delenv("COHERE_BASE_URL")
        with pytest.raises(ValueError, match="COHERE_BASE_URL"):
            mod._get_endpoint({})

    def test_rejects_http(self, monkeypatch):
        monkeypatch.setenv("COHERE_BASE_URL", "http://insecure.example.com")
        with pytest.raises(ValueError, match="HTTPS"):
            mod._get_endpoint({})


class TestApiKey:
    def test_default_env(self):
        assert mod._get_api_key({}) == "secret"

    def test_custom_env(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "k2")
        config = {"api_key_env": "MY_KEY"}  # pragma: allowlist secret
        assert mod._get_api_key(config) == "k2"

    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("COHERE_API_KEY")
        with pytest.raises(ValueError, match="COHERE_API_KEY"):
            mod._get_api_key({})


class TestParse:
    def test_orders_by_index(self):
        data = {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.1},
            ]
        }
        assert mod.parse_rerank_response(data, 2) == [0.1, 0.9]

    def test_accepts_score_key(self):
        data = {"results": [{"index": 0, "score": 0.5}]}
        assert mod.parse_rerank_response(data, 1) == [0.5]

    def test_plain_score_list(self):
        assert mod.parse_rerank_response({"scores": [0.2, 0.7]}, 2) == [0.2, 0.7]

    def test_missing_docs_rank_below_returned(self):
        data = {"results": [{"index": 1, "relevance_score": 0.4}]}
        scores = mod.parse_rerank_response(data, 3)
        assert scores[1] == 0.4
        assert scores[0] < 0.4 and scores[2] < 0.4
        assert all(s == s and abs(s) != float("inf") for s in scores)

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"results": []},
            {"results": [{"index": 5, "relevance_score": 1.0}]},
            {"results": [{"index": 0}]},
            {"results": ["bad"]},
            {"scores": [0.1]},
        ],
    )
    def test_invalid_raises(self, data):
        with pytest.raises(ValueError):
            mod.parse_rerank_response(data, 2)


class TestRerank:
    def test_success_and_request_shape(self):
        payload = {"results": [{"index": 0, "relevance_score": 0.3}]}
        with patch(f"{MODULE}.urlopen", return_value=_response(payload)) as urlopen:
            scores = mod.rerank_with_cohere_compatible("q", ["d"], "model-x", {})
        assert scores == [0.3]
        request = urlopen.call_args.args[0]
        assert request.full_url == "https://api.example.com/v2/rerank"
        assert request.get_header("Authorization") == "Bearer secret"
        body = json.loads(request.data)
        assert body == {
            "model": "model-x",
            "query": "q",
            "documents": ["d"],
            "top_n": 1,
        }

    def test_timeout_from_config(self):
        payload = {"results": [{"index": 0, "relevance_score": 0.3}]}
        with patch(f"{MODULE}.urlopen", return_value=_response(payload)) as urlopen:
            mod.rerank_with_cohere_compatible("q", ["d"], "m", {"timeout": 7})
        assert urlopen.call_args.kwargs["timeout"] == 7

    @pytest.mark.parametrize("code", [429, 500, 503])
    def test_transient_http_errors(self, code):
        with patch(f"{MODULE}.urlopen", side_effect=_http_error(code)):
            with pytest.raises(RerankerUnavailableError):
                mod.rerank_with_cohere_compatible("q", ["d"], "m", {})

    @pytest.mark.parametrize("code", [400, 401, 404])
    def test_client_errors_are_value_errors(self, code):
        with patch(f"{MODULE}.urlopen", side_effect=_http_error(code)):
            with pytest.raises(ValueError, match=str(code)):
                mod.rerank_with_cohere_compatible("q", ["d"], "m", {})

    @pytest.mark.parametrize("exc", [URLError("down"), TimeoutError("slow")])
    def test_network_errors_are_transient(self, exc):
        with patch(f"{MODULE}.urlopen", side_effect=exc):
            with pytest.raises(RerankerUnavailableError):
                mod.rerank_with_cohere_compatible("q", ["d"], "m", {})
