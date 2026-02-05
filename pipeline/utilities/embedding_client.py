"""Client for remote embedding server calls."""

import logging
import os
from typing import Generator, Iterable

import numpy as np
import requests

logger = logging.getLogger(__name__)


class RemoteEmbeddingClient:  # pylint: disable=too-few-public-methods
    """
    Client for interacting with the Infinity embedding server.
    Mimics the interface of fastembed.TextEmbedding for compatibility.
    """

    def __init__(self, base_url: str, model_name: str):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.request_timeout = int(os.getenv("EMBEDDING_REQUEST_TIMEOUT", "120"))

    def embed(
        self, documents: Iterable[str], batch_size: int = None
    ) -> Generator[np.ndarray, None, None]:
        """
        Generate embeddings using the remote Infinity server.
        Yields numpy arrays to mimic fastembed interface.
        """
        docs = list(documents) if not isinstance(documents, list) else documents
        if not docs:
            return

        url = f"{self.base_url}/embeddings"
        for batch in _iter_batches(docs, batch_size):
            try:
                payload = {"model": self.model_name, "input": batch}
                response = requests.post(
                    url, json=payload, timeout=self.request_timeout
                )
                if response.status_code != 200:
                    raise requests.exceptions.HTTPError(
                        f"{response.status_code} Client Error: {response.reason} for url: {url} | "
                        f"Response: {response.text}",
                        response=response,
                    )
                data = response.json()
                embeddings = [item["embedding"] for item in data["data"]]
                for emb in embeddings:
                    yield np.array(emb, dtype=np.float32)
            except (requests.exceptions.RequestException, ValueError, KeyError) as exc:
                logger.error(
                    "Remote embedding failed for batch of size %s: %s",
                    len(batch),
                    exc,
                )
                raise


def _iter_batches(
    documents: list, batch_size: int = None
) -> Generator[list, None, None]:
    if not batch_size or batch_size <= 0:
        yield documents
        return
    for start in range(0, len(documents), batch_size):
        yield documents[start : start + batch_size]
