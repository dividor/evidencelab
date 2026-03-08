"""Google Vertex AI embedding client."""

import json
import logging
import os
import time
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import requests

logger = logging.getLogger(__name__)


def _load_gcp_project_id() -> str:
    """Load GCP project ID from credentials file or environment."""
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        return project_id

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path and os.path.exists(creds_path):
        with open(creds_path, encoding="utf-8") as f:
            creds = json.load(f)
            project_id = creds.get("project_id")
            if project_id:
                return project_id

    raise ValueError(
        "GCP project ID not found. Set GOOGLE_CLOUD_PROJECT or "
        "GOOGLE_APPLICATION_CREDENTIALS pointing to a service account JSON."
    )


def _get_gcp_access_token() -> str:
    """Get a valid access token using google-auth."""
    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials.token


class GoogleVertexEmbeddingClient:
    """Client for Google Vertex AI Embeddings API.

    Implements a compatible interface with AzureEmbeddingClient / FastEmbed's
    TextEmbedding so it can be used interchangeably in the pipeline.
    """

    def __init__(
        self,
        model_id: str,
        project_id: Optional[str] = None,
        location: str = "us-central1",
        batch_size: int = 5,
        max_retries: int = 3,
        output_dimensionality: Optional[int] = None,
    ):
        self.model_id = model_id
        self.project_id = project_id or _load_gcp_project_id()
        self.location = location
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.output_dimensionality = output_dimensionality

        self.base_url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/"
            f"projects/{self.project_id}/locations/{self.location}/"
            f"publishers/google/models/{self.model_id}:predict"
        )
        logger.info(
            "GoogleVertexEmbeddingClient: model=%s, project=%s, location=%s, "
            "output_dimensionality=%s",
            self.model_id,
            self.project_id,
            self.location,
            self.output_dimensionality,
        )

    def embed(
        self, documents: Iterable[str], batch_size: int = 0, **kwargs: Any
    ) -> Iterable[np.ndarray]:
        """Generate embeddings for a list of documents.

        Args:
            documents: Iterable of text strings to embed.
            batch_size: Optional override for internal batch size.

        Yields:
            np.ndarray: Embedding vectors.
        """
        texts = list(documents)
        if not texts:
            return
        self._validate_texts(texts)

        req_batch_size = batch_size if batch_size > 0 else self.batch_size
        total_texts = len(texts)
        logger.info(
            "GoogleVertexEmbeddingClient: Embedding %s texts (batch_size=%s, model=%s)",
            total_texts,
            req_batch_size,
            self.model_id,
        )

        for i in range(0, total_texts, req_batch_size):
            batch = texts[i : i + req_batch_size]
            embeddings = self._call_api(batch)
            for vec in embeddings:
                yield np.array(vec, dtype=np.float32)

    def _validate_texts(self, texts: List[str]) -> None:
        invalid_indices: list[int] = []
        invalid_samples: list[str] = []
        for idx, text in enumerate(texts):
            if not isinstance(text, str):
                invalid_indices.append(idx)
                if len(invalid_samples) < 3:
                    invalid_samples.append(f"{idx}:<non-str:{type(text).__name__}>")
                continue
            if not text.strip():
                invalid_indices.append(idx)
                if len(invalid_samples) < 3:
                    invalid_samples.append(f"{idx}:{text!r}")
        if invalid_indices:
            sample_text = ", ".join(invalid_samples)
            raise ValueError(
                "GoogleVertexEmbeddingClient received invalid input texts "
                f"(count={len(invalid_indices)}). Sample(s): {sample_text}"
            )

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        """Make request to Vertex AI predict endpoint with retry logic."""
        token = _get_gcp_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(texts)

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(
                        "Rate limited by Vertex AI. Retrying in %ss...", retry_after
                    )
                    time.sleep(retry_after)
                    continue
                if response.status_code != 200:
                    error_msg = (
                        f"Vertex AI Error {response.status_code}: {response.reason}"
                    )
                    try:
                        error_msg += f" - {response.json()}"
                    except Exception:
                        error_msg += f" - {response.text[:500]}"
                    if 400 <= response.status_code < 500:
                        raise requests.exceptions.HTTPError(
                            error_msg, response=response
                        )
                    raise requests.exceptions.HTTPError(error_msg, response=response)
                return self._parse_embeddings(response.json())
            except requests.exceptions.RequestException as exc:
                if attempt >= self.max_retries - 1:
                    logger.error(
                        "Vertex AI API request failed after %s attempts.",
                        self.max_retries,
                    )
                    raise
                if (
                    hasattr(exc, "response")
                    and exc.response is not None
                    and 400 <= exc.response.status_code < 500
                ):
                    raise
                wait_time = 2 * (attempt + 1)
                logger.warning(
                    "Vertex AI API request failed (%s). Retrying in %ss...",
                    exc,
                    wait_time,
                )
                time.sleep(wait_time)

        raise RuntimeError("Unreachable code reached in _call_api")

    def _build_payload(self, texts: List[str]) -> Dict[str, Any]:
        """Build the Vertex AI predict request payload."""
        instances = [{"content": text} for text in texts]
        payload: Dict[str, Any] = {"instances": instances}
        if self.output_dimensionality:
            payload["parameters"] = {"outputDimensionality": self.output_dimensionality}
        return payload

    def _parse_embeddings(self, data: Dict[str, Any]) -> List[List[float]]:
        """Extract embedding vectors from the Vertex AI response."""
        predictions = data.get("predictions", [])
        return [pred["embeddings"]["values"] for pred in predictions]
