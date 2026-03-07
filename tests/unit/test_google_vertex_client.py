"""Unit tests for GoogleVertexEmbeddingClient."""

import json

import numpy as np
import pytest

from pipeline.utilities.google_vertex_client import (
    GoogleVertexEmbeddingClient,
    _load_gcp_project_id,
)

# --- _load_gcp_project_id tests ---


def test_load_gcp_project_id_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    assert _load_gcp_project_id() == "my-project"


def test_load_gcp_project_id_from_creds_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"project_id": "file-project"}))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    assert _load_gcp_project_id() == "file-project"


def test_load_gcp_project_id_raises_when_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(ValueError, match="GCP project ID not found"):
        _load_gcp_project_id()


def test_load_gcp_project_id_raises_when_creds_file_missing_project_id(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"type": "service_account"}))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    with pytest.raises(ValueError, match="GCP project ID not found"):
        _load_gcp_project_id()


# --- GoogleVertexEmbeddingClient construction ---


def test_client_init_sets_attributes(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-proj")
    client = GoogleVertexEmbeddingClient(
        model_id="gemini-embedding-001",
        output_dimensionality=1536,
    )
    assert client.model_id == "gemini-embedding-001"
    assert client.project_id == "test-proj"
    assert client.output_dimensionality == 1536
    assert "gemini-embedding-001:predict" in client.base_url
    assert "test-proj" in client.base_url


def test_client_init_with_explicit_project():
    client = GoogleVertexEmbeddingClient(
        model_id="gemini-embedding-001",
        project_id="explicit-proj",
    )
    assert client.project_id == "explicit-proj"


# --- _build_payload tests ---


def test_build_payload_without_dimensionality(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m")
    payload = client._build_payload(["hello", "world"])
    assert payload == {
        "instances": [{"content": "hello"}, {"content": "world"}],
    }
    assert "parameters" not in payload


def test_build_payload_with_dimensionality(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m", output_dimensionality=768)
    payload = client._build_payload(["hello"])
    assert payload == {
        "instances": [{"content": "hello"}],
        "parameters": {"outputDimensionality": 768},
    }


# --- _parse_embeddings tests ---


def test_parse_embeddings(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m")
    data = {
        "predictions": [
            {"embeddings": {"values": [0.1, 0.2, 0.3]}},
            {"embeddings": {"values": [0.4, 0.5, 0.6]}},
        ]
    }
    result = client._parse_embeddings(data)
    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_parse_embeddings_empty(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m")
    result = client._parse_embeddings({"predictions": []})
    assert result == []


# --- _validate_texts tests ---


def test_validate_texts_raises_on_empty_string(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m")
    with pytest.raises(ValueError, match="invalid input texts"):
        client._validate_texts(["valid", "", "also valid"])


def test_validate_texts_raises_on_non_string(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m")
    with pytest.raises(ValueError, match="invalid input texts"):
        client._validate_texts(["valid", 123])  # type: ignore[list-item]


def test_validate_texts_passes_for_valid(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m")
    client._validate_texts(["hello", "world"])  # should not raise


# --- embed tests (mocked API) ---


def test_embed_yields_numpy_arrays(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m", batch_size=2)

    mock_response = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    call_count = {"n": 0}

    def fake_call_api(texts):
        start = call_count["n"]
        call_count["n"] += len(texts)
        return mock_response[start : start + len(texts)]

    monkeypatch.setattr(client, "_call_api", fake_call_api)

    results = list(client.embed(["a", "b", "c"]))
    assert len(results) == 3
    assert all(isinstance(r, np.ndarray) for r in results)
    assert results[0].dtype == np.float32
    np.testing.assert_array_almost_equal(results[0], [0.1, 0.2])


def test_embed_empty_returns_nothing(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    client = GoogleVertexEmbeddingClient(model_id="m")
    results = list(client.embed([]))
    assert results == []
