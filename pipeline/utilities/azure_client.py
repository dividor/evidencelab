"""Azure Foundry embedding client."""

import logging
import time
from typing import Iterable, List

import numpy as np
import requests

logger = logging.getLogger(__name__)


class AzureEmbeddingClient:  # pylint: disable=too-few-public-methods
    """
    Client for Azure Foundry Embeddings API.
    Implements a compatible interface with FastEmbed's TextEmbedding.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        api_key: str,
        endpoint: str,
        deployment_name: str,
        batch_size: int = 8,
        max_retries: int = 3,
    ):
        """
        Initialize Azure Foundry client.

        Args:
            api_key: Azure Foundry API Key
            endpoint: Azure Foundry Endpoint (e.g., https://my-resource.openai.azure.com/)
            deployment_name: Name of the deployment (e.g., text-embedding-3-small)
            batch_size: Max vectors per request (default 8)
            max_retries: Number of retries for failed requests
        """
        self.api_key = api_key
        # Ensure endpoint has no trailing slash for clean URL construction
        self.endpoint = endpoint.rstrip("/")
        self.deployment_name = deployment_name
        self.batch_size = batch_size
        self.max_retries = max_retries

        # Store for compatibility/logging
        self.base_url = f"{self.endpoint}/openai/deployments/{self.deployment_name}"

    def embed(
        self, documents: Iterable[str], batch_size: int = 0, **kwargs
    ) -> Iterable[np.ndarray]:
        """
        Generate embeddings for a list of documents.

        Args:
            documents: List/Iterable of text strings to embed.
            batch_size: Optional override for internal batch size (defaults to init value).

        Yields:
            np.ndarray: Embedding vectors.
        """
        texts = list(documents)
        if not texts:
            return
        self._validate_texts(texts)

        # Use configured batch size if not overridden
        req_batch_size = batch_size if batch_size > 0 else self.batch_size

        total_texts = len(texts)
        logger.info(
            "AzureEmbeddingClient: Embedding %s texts (batch_size=%s, model=%s)",
            total_texts,
            req_batch_size,
            self.deployment_name,
        )

        _ = kwargs
        for i in range(0, total_texts, req_batch_size):
            batch = texts[i : i + req_batch_size]
            try:
                embeddings = self._call_api(batch)
                for vec in embeddings:
                    yield np.array(vec, dtype=np.float32)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Failed to embed batch starting at index %s: %s", i, e)
                raise

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
                "AzureEmbeddingClient received invalid input texts "
                f"(count={len(invalid_indices)}). Sample(s): {sample_text}"
            )

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        """
        Make direct HTTP request to Azure Foundry.
        """
        url, headers, payload = self._build_request(texts)
        for attempt in range(self.max_retries):
            try:
                response = self._post_request(url, headers, payload)
                if self._handle_rate_limit(response):
                    continue
                self._raise_for_http_error(response)
                return self._parse_embeddings(response)
            except requests.exceptions.RequestException as exc:
                if not self._should_retry(exc, attempt):
                    raise

        raise RuntimeError("Unreachable code reached in _call_api")

    def _build_request(self, texts: List[str]) -> tuple[str, dict, dict]:
        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment_name}/embeddings"
            "?api-version=2023-05-15"
        )
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }
        payload = {"input": texts}
        return url, headers, payload

    def _post_request(
        self, url: str, headers: dict, payload: dict
    ) -> requests.Response:
        return requests.post(url, headers=headers, json=payload, timeout=30)

    def _handle_rate_limit(self, response: requests.Response) -> bool:
        if response.status_code != 429:
            return False
        retry_after = int(response.headers.get("Retry-After", 5))
        logger.warning("Rate limited by Azure. Retrying in %ss...", retry_after)
        time.sleep(retry_after)
        return True

    def _raise_for_http_error(self, response: requests.Response) -> None:
        if response.status_code == 200:
            return
        error_msg = f"Azure Error {response.status_code}: {response.reason}"
        error_msg = self._append_error_details(error_msg, response)
        raise requests.exceptions.HTTPError(error_msg, response=response)

    def _append_error_details(self, error_msg: str, response: requests.Response) -> str:
        try:
            error_data = response.json()
            if "error" in error_data:
                error_msg += f" - {self._format_error(error_data['error'])}"
            else:
                error_msg += f" - {error_data}"
        except Exception:  # pylint: disable=broad-exception-caught
            error_msg += f" - {response.text}"
        return error_msg

    def _format_error(self, err_obj: object) -> str:
        if isinstance(err_obj, dict):
            msg = err_obj.get("message") or str(err_obj)
            code = err_obj.get("code")
            result = f"{code}: {msg}" if code else msg
            if "innererror" in err_obj:
                result += f" ({self._format_error(err_obj['innererror'])})"
            return result
        return str(err_obj)

    def _parse_embeddings(self, response: requests.Response) -> List[List[float]]:
        data = response.json()
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]

    def _should_retry(
        self, exc: requests.exceptions.RequestException, attempt: int
    ) -> bool:
        if attempt >= self.max_retries - 1:
            logger.error(
                "Azure API request failed after %s attempts.", self.max_retries
            )
            return False
        if exc.response is not None and 400 <= exc.response.status_code < 500:
            logger.error("Azure Client Error (Fatal): %s", exc)
            return False
        wait_time = 2 * (attempt + 1)
        logger.warning(
            "Azure API request failed (%s). Retrying in %ss...",
            exc,
            wait_time,
        )
        time.sleep(wait_time)
        return True
