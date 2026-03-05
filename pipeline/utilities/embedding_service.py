"""Centralized embedding service for all model access.

All embedding model access in the pipeline goes through this service.
No module should load embedding models directly — they must use
EmbeddingService to obtain a client.

Routing:
- HuggingFace models: served via the Infinity embedding server
  (local or remote, configured via EMBEDDING_API_URL)
- Azure Foundry models: passthrough to Azure API
"""

import logging
import os
from typing import Any, Dict, Optional

from pipeline.db import DB_VECTORS
from pipeline.utilities.azure_client import AzureEmbeddingClient
from pipeline.utilities.embedding_client import RemoteEmbeddingClient

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Centralized provider of embedding model clients.

    Resolves model names (registry keys like ``'azure_small'`` or full
    model IDs like ``'intfloat/multilingual-e5-large'``) to the
    appropriate client, caching instances so that multiple processors
    sharing the same model reuse a single client.
    """

    def __init__(self, embedding_api_url: Optional[str] = None):
        self._embedding_api_url = embedding_api_url or os.getenv("EMBEDDING_API_URL")
        self._clients: Dict[str, Any] = {}

    def get_model(self, model_name: str) -> Any:
        """Return an embedding client for *model_name*.

        *model_name* can be either a registry key in
        ``supported_embedding_models`` (e.g. ``'azure_small'``,
        ``'e5_large'``) or a full model ID (e.g.
        ``'intfloat/multilingual-e5-large'``).

        Clients are cached so repeated calls with the same name return
        the same object.
        """
        if model_name in self._clients:
            return self._clients[model_name]

        # Try registry key first
        vec_config = DB_VECTORS.get(model_name)
        if vec_config:
            client = self._create_client(model_name, vec_config)
            self._clients[model_name] = client
            return client

        # Try matching by model_id
        for reg_name, reg_config in DB_VECTORS.items():
            if reg_config.get("model_id") == model_name:
                return self.get_model(reg_name)

        # Assume HuggingFace model served by embedding server
        return self._create_huggingface_client(model_name, model_name)

    def _create_client(self, name: str, vec_config: Dict[str, Any]) -> Any:
        source = vec_config.get("source", "huggingface")
        model_id = vec_config["model_id"]

        if source == "azure_foundry":
            return self._create_azure_client(name, model_id)
        if source == "huggingface":
            return self._create_huggingface_client(name, model_id)

        raise ValueError(
            f"Unsupported embedding model source '{source}' for model '{name}'. "
            "Supported sources: 'huggingface', 'azure_foundry'."
        )

    def _create_azure_client(self, name: str, model_id: str) -> AzureEmbeddingClient:
        api_key = os.getenv("AZURE_FOUNDRY_KEY")
        endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")
        if not api_key or not endpoint:
            raise ValueError(
                f"Missing AZURE_FOUNDRY_KEY or AZURE_FOUNDRY_ENDPOINT "
                f"for Azure model '{name}' ({model_id})."
            )
        logger.info(
            "EmbeddingService: created Azure client for '%s' (%s)", name, model_id
        )
        return AzureEmbeddingClient(
            api_key=api_key,
            endpoint=endpoint,
            deployment_name=model_id,
        )

    def _create_huggingface_client(
        self, name: str, model_id: str
    ) -> RemoteEmbeddingClient:
        if not self._embedding_api_url:
            raise ValueError(
                f"EMBEDDING_API_URL not set — cannot create client for "
                f"HuggingFace model '{name}' ({model_id}). "
                "Ensure the embedding server is running."
            )
        logger.info(
            "EmbeddingService: created remote client for '%s' (%s) via %s",
            name,
            model_id,
            self._embedding_api_url,
        )
        return RemoteEmbeddingClient(
            base_url=self._embedding_api_url,
            model_name=model_id,
        )
