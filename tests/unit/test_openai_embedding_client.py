"""Tests for the OpenAI-compatible embedding client."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import requests

from pipeline.utilities.openai_embedding_client import OpenAIEmbeddingClient

MODULE = "pipeline.utilities.openai_embedding_client"


def _resp(status=200, data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.json.return_value = {"data": data or []}
    return resp


def _items(n, offset=0):
    return [{"index": i, "embedding": [float(i + offset), 0.0]} for i in range(n)]


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch(f"{MODULE}.time.sleep") as sleep:
        yield sleep


def _client(**kw):
    return OpenAIEmbeddingClient("https://api.example.com/v1/", "m", **kw)


def test_embed_returns_float32_arrays_in_order():
    items = list(reversed(_items(3)))  # API returns out of order
    with patch(f"{MODULE}.requests.post", return_value=_resp(data=items)) as post:
        out = list(_client(api_key="k").embed(["a", "b", "c"]))
    assert [v[0] for v in out] == [0.0, 1.0, 2.0]
    assert all(v.dtype == np.float32 for v in out)
    assert post.call_args.args[0] == "https://api.example.com/v1/embeddings"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer k"


def test_no_authorization_header_without_key():
    with patch(f"{MODULE}.requests.post", return_value=_resp(data=_items(1))) as post:
        list(_client().embed(["a"]))
    assert "Authorization" not in post.call_args.kwargs["headers"]


def test_batches():
    with patch(
        f"{MODULE}.requests.post",
        side_effect=[_resp(data=_items(2)), _resp(data=_items(1))],
    ) as post:
        out = list(_client().embed(["a", "b", "c"], batch_size=2))
    assert len(out) == 3
    assert post.call_count == 2


def test_empty_input():
    with patch(f"{MODULE}.requests.post") as post:
        assert list(_client().embed([])) == []
    post.assert_not_called()


def test_retries_transient_then_succeeds(_no_sleep):
    responses = [_resp(status=429, text="slow down"), _resp(data=_items(1))]
    with patch(f"{MODULE}.requests.post", side_effect=responses) as post:
        out = list(_client().embed(["a"]))
    assert len(out) == 1
    assert post.call_count == 2
    _no_sleep.assert_called_once()


def test_retries_connection_errors():
    side = [requests.ConnectionError("down"), _resp(data=_items(1))]
    with patch(f"{MODULE}.requests.post", side_effect=side):
        assert len(list(_client().embed(["a"]))) == 1


def test_gives_up_after_max_retries():
    with patch(
        f"{MODULE}.requests.post", return_value=_resp(status=503, text="x")
    ) as post:
        with pytest.raises(requests.exceptions.RequestException):
            list(_client().embed(["a"]))
    assert post.call_count == 4


def test_client_error_not_retried_and_text_truncated():
    with patch(
        f"{MODULE}.requests.post", return_value=_resp(status=401, text="E" * 5000)
    ) as post:
        with pytest.raises(requests.exceptions.HTTPError) as err:
            list(_client().embed(["a"]))
    assert post.call_count == 1
    assert len(str(err.value)) < 600


def test_wrong_vector_count_raises():
    with patch(f"{MODULE}.requests.post", return_value=_resp(data=_items(1))):
        with pytest.raises(ValueError, match="vectors"):
            list(_client().embed(["a", "b"]))
