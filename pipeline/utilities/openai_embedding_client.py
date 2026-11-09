"""Embedding client for any OpenAI-compatible ``/embeddings`` endpoint.

Works with OpenAI and with providers exposing the same API (Infomaniak,
vLLM, Ollama, LiteLLM, ...). Exposes the same ``embed`` surface as the other
embedding clients (a generator of ``float32`` numpy vectors).
"""

import logging
import os
import time
from typing import Any, Dict, Generator, Iterable, List, Optional

import numpy as np
import requests

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 16
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenAIEmbeddingClient:
    """Client for an OpenAI-compatible embeddings API."""

    def __init__(self, base_url: str, model_name: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key
        self.request_timeout = int(os.getenv("EMBEDDING_REQUEST_TIMEOUT", "120"))

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, batch: List[str]) -> Dict[str, Any]:
        """POST one batch, retrying transient failures with backoff."""
        url = f"{self.base_url}/embeddings"
        payload = {"model": self.model_name, "input": batch}
        last_error: Optional[str] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=self.request_timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = str(exc)
            else:
                if response.status_code == 200:
                    return response.json()
                detail = (
                    f"{response.status_code} for url: {url} | {response.text[:300]}"
                )
                if response.status_code not in _RETRYABLE_STATUS:
                    raise requests.exceptions.HTTPError(detail, response=response)
                last_error = detail
            if attempt < MAX_RETRIES:
                delay = RETRY_BACKOFF_SECONDS * (2**attempt)
                logger.warning(
                    "Embedding request failed (%s); retry %d/%d in %.0fs",
                    last_error,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
        raise requests.exceptions.RequestException(
            f"Embedding request failed after {MAX_RETRIES + 1} attempts: {last_error}"
        )

    def embed(
        self, documents: Iterable[str], batch_size: Optional[int] = None
    ) -> Generator[np.ndarray, None, None]:
        docs = list(documents) if not isinstance(documents, list) else documents
        if not docs:
            return

        bs = batch_size if batch_size and batch_size > 0 else DEFAULT_BATCH_SIZE
        for i in range(0, len(docs), bs):
            batch = docs[i : i + bs]
            try:
                data = self._post(batch)["data"]
                # The API may return items out of order; "index" restores it.
                data = sorted(data, key=lambda item: item.get("index", 0))
                if len(data) != len(batch):
                    raise ValueError(
                        f"Embedding API returned {len(data)} vectors "
                        f"for {len(batch)} inputs."
                    )
                vectors = [
                    np.array(item["embedding"], dtype=np.float32) for item in data
                ]
            except (requests.exceptions.RequestException, ValueError, KeyError) as exc:
                logger.error(
                    "OpenAI-compatible embedding failed for batch of size %s: %s",
                    len(batch),
                    exc,
                )
                raise
            yield from vectors
