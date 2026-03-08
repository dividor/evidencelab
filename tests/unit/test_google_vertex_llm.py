"""Unit tests for Google Vertex AI LLM provider in llm_factory."""

import json
from unittest.mock import MagicMock, patch

import pytest

import utils.llm_factory as llm_factory


def test_create_google_vertex_llm_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-proj")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west1")

    with patch.object(llm_factory, "ChatVertexAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        llm_factory._create_google_vertex_llm(
            model="gemini-2.5-flash",
            temperature=0.2,
            max_tokens=2000,
        )

    mock_cls.assert_called_once_with(
        model="gemini-2.5-flash",
        temperature=0.2,
        max_tokens=2000,
        project="test-proj",
        location="europe-west1",
        thinking_budget=0,
    )


def test_create_google_vertex_llm_from_creds_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"project_id": "creds-project"}))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    with patch.object(llm_factory, "ChatVertexAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        llm_factory._create_google_vertex_llm(
            model="gemini-2.5-pro",
            temperature=0.0,
            max_tokens=4000,
        )

    mock_cls.assert_called_once_with(
        model="gemini-2.5-pro",
        temperature=0.0,
        max_tokens=4000,
        project="creds-project",
        location="us-central1",
        thinking_budget=0,
    )


def test_create_google_vertex_llm_no_thinking_for_non_25(monkeypatch):
    """Gemini 2.0 models should NOT get thinking_budget kwarg."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-proj")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    with patch.object(llm_factory, "ChatVertexAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        llm_factory._create_google_vertex_llm(
            model="gemini-2.0-flash",
            temperature=0.2,
            max_tokens=2000,
        )

    mock_cls.assert_called_once_with(
        model="gemini-2.0-flash",
        temperature=0.2,
        max_tokens=2000,
        project="test-proj",
        location="us-central1",
    )


def test_create_google_vertex_llm_raises_without_project(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    with pytest.raises(ValueError, match="Google Cloud project not found"):
        llm_factory._create_google_vertex_llm("gemini-2.5-flash", 0.7, 500)


def test_create_google_vertex_llm_default_location(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

    with patch.object(llm_factory, "ChatVertexAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        llm_factory._create_google_vertex_llm("gemini-2.5-flash", 0.7, 500)

    call_kwargs = mock_cls.call_args[1]
    assert call_kwargs["location"] == "us-central1"


def test_create_llm_for_provider_routes_google_vertex(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")

    with patch.object(llm_factory, "ChatVertexAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        llm_factory._create_llm_for_provider(
            provider="google_vertex",
            model="gemini-2.5-flash",
            temperature=0.5,
            max_tokens=1000,
            inference_provider=None,
        )

    mock_cls.assert_called_once()


def test_create_llm_for_provider_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        llm_factory._create_llm_for_provider(
            provider="nonexistent",
            model="m",
            temperature=0.5,
            max_tokens=500,
            inference_provider=None,
        )
