import logging
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
import requests

from pipeline import __version__
from pipeline.utilities import azure_client as azure_client_module
from pipeline.utilities import embedding_server as embedding_server_module
from pipeline.utilities.azure_client import AzureEmbeddingClient
from pipeline.utilities.embedding_client import RemoteEmbeddingClient
from pipeline.utilities.embedding_server import EmbeddingServerManager
from pipeline.utilities.id_utils import generate_doc_id
from pipeline.utilities.logging_utils import ContextFilter, _log_context
from pipeline.utilities.sanitization import sanitize_filename
from pipeline.utilities.text_cleaning import clean_text, fix_macroman_mojibake


class DummyResponse:
    def __init__(
        self,
        status_code: int,
        json_data: dict,
        reason: str = "OK",
        text: str = "",
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self._json_data = json_data
        self.reason = reason
        self.text = text
        self.headers = headers or {}
        self.response = self

    def json(self):
        return self._json_data


def test_pipeline_version_is_set():
    assert isinstance(__version__, str)
    assert __version__


def test_generate_doc_id_is_deterministic():
    first = generate_doc_id("https://example.com/doc")
    second = generate_doc_id("https://example.com/doc")
    other = generate_doc_id("https://example.com/other")

    assert first == second
    assert first != other
    assert uuid.UUID(first).version == 5


def test_clean_text_repairs_replacement_character():
    assert clean_text("Na\ufffdonal") == "National"
    assert clean_text("Naonal") == "National"
    assert clean_text("mo\ufffdl") == "motil"


def test_fix_macroman_mojibake_repairs_french_text():
    assert (
        fix_macroman_mojibake("parit\u017d et \u017dgalit\u00e9")
        == "parit\u00e9 et \u00e9galit\u00e9"
    )
    assert fix_macroman_mojibake("l\u02c6 parit\u017d") == "l\u00e0 parit\u00e9"


def test_fix_macroman_mojibake_skips_below_threshold():
    assert fix_macroman_mojibake("\u017dilina city") == "\u017dilina city"
    assert fix_macroman_mojibake("") == ""
    assert fix_macroman_mojibake("plain text") == "plain text"


def test_fix_macroman_mojibake_contextual_apostrophe():
    # Õ between word chars -> right single quote; needs >=2 strong markers
    assert (
        fix_macroman_mojibake("l\u00d5\u017dconomie du d\u017dveloppement")
        == "l\u2019\u00e9conomie du d\u00e9veloppement"
    )
    # Õ at start (not between word chars) stays as Õ
    assert (
        fix_macroman_mojibake("\u00d5 is \u017d and \u017d")
        == "\u00d5 is \u00e9 and \u00e9"
    )


def test_clean_text_includes_macroman_fix():
    assert (
        clean_text("parit\u017d et \u017dgalit\u00e9")
        == "parit\u00e9 et \u00e9galit\u00e9"
    )


def test_sanitize_filename_rules():
    assert sanitize_filename("  My File..Name!! ") == "my_file.name"
    assert sanitize_filename("") == "untitled"
    assert sanitize_filename("...__") == "untitled"


def test_context_filter_injects_doc_id():
    record = logging.LogRecord("test", logging.INFO, __file__, 10, "msg", (), None)
    context_filter = ContextFilter()

    if hasattr(_log_context, "doc_id"):
        delattr(_log_context, "doc_id")
    context_filter.filter(record)
    assert record.doc_id == "N/A"

    _log_context.doc_id = "doc-123"
    context_filter.filter(record)
    assert record.doc_id == "doc-123"


def test_remote_embedding_client_yields_vectors(monkeypatch):
    captured = {}

    def fake_post(url, json, **kwargs):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = kwargs.get("timeout")
        return DummyResponse(
            200,
            {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]},
        )

    monkeypatch.setattr(requests, "post", fake_post)
    client = RemoteEmbeddingClient("http://server", "model-x")
    vectors = list(client.embed(["a", "b"]))

    assert captured["url"] == "http://server/embeddings"
    assert captured["payload"]["model"] == "model-x"
    assert len(vectors) == 2
    assert np.allclose(vectors[0], np.array([0.1, 0.2], dtype=np.float32))


def test_remote_embedding_client_raises_on_error(monkeypatch):
    def fake_post(url, json, **kwargs):
        return DummyResponse(500, {"error": "bad"}, reason="FAIL", text="bad")

    monkeypatch.setattr(requests, "post", fake_post)
    client = RemoteEmbeddingClient("http://server", "model-x")

    with pytest.raises(requests.exceptions.HTTPError):
        list(client.embed(["a"]))


def test_azure_embedding_client_batches_texts(monkeypatch):
    calls: list[list[str]] = []

    def fake_call_api(texts):
        calls.append(texts)
        return [[0.1, 0.2] for _ in texts]

    client = AzureEmbeddingClient("key", "https://azure", "deploy", batch_size=2)
    monkeypatch.setattr(client, "_call_api", fake_call_api)
    vectors = list(client.embed(["a", "b", "c"]))

    assert [len(batch) for batch in calls] == [2, 1]
    assert len(vectors) == 3


def test_azure_embedding_client_rejects_invalid_inputs(monkeypatch):
    client = AzureEmbeddingClient("key", "https://azure", "deploy", batch_size=2)

    def fake_call_api(_texts):
        pytest.fail("_call_api should not be called for invalid inputs")

    monkeypatch.setattr(client, "_call_api", fake_call_api)

    with pytest.raises(ValueError):
        list(client.embed(["ok", ""]))


def test_azure_embedding_client_handles_rate_limit(monkeypatch):
    responses = [
        DummyResponse(429, {}, headers={"Retry-After": "1"}),
        DummyResponse(
            200,
            {
                "data": [
                    {"index": 1, "embedding": [0.2]},
                    {"index": 0, "embedding": [0.1]},
                ]
            },
        ),
    ]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    sleeps = []
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(azure_client_module.time, "sleep", lambda s: sleeps.append(s))

    client = AzureEmbeddingClient("key", "https://azure", "deploy", max_retries=2)
    embeddings = client._call_api(["a", "b"])

    assert sleeps == [1]
    assert embeddings == [[0.1], [0.2]]


def test_embedding_server_is_running(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse(200, {}))
    manager = EmbeddingServerManager()
    assert manager.is_running() is True


def test_embedding_server_is_running_false_on_exception(monkeypatch):
    def raise_request(*args, **kwargs):
        raise requests.RequestException("nope")

    monkeypatch.setattr(requests, "get", raise_request)
    manager = EmbeddingServerManager()
    assert manager.is_running() is False


def test_embedding_server_start_remote_does_not_spawn(monkeypatch):
    manager = EmbeddingServerManager()
    manager.base_url = "http://embedding-server:7997"
    monkeypatch.setattr(manager, "is_running", lambda: False)
    monkeypatch.setattr(
        embedding_server_module.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("Popen should not be called"),
    )

    manager.start()


def test_wait_for_healthy_raises_when_process_dies(monkeypatch):
    manager = EmbeddingServerManager()
    manager.process = SimpleNamespace(poll=lambda: 1)
    monkeypatch.setattr(manager, "is_running", lambda: False)

    with pytest.raises(RuntimeError):
        manager._wait_for_healthy(timeout=1)
