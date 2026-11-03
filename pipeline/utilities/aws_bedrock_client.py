"""Amazon Bedrock embeddings and reranking.

Credentials and region come from the standard AWS sources: the
``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN`` and
``AWS_REGION`` environment variables, an AWS profile, or the ECS task role.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Iterable, List, Optional

import boto3
import numpy as np
from botocore.config import Config

logger = logging.getLogger(__name__)

# Bedrock throttles bursts; adaptive retries back off and retry them.
_RETRY_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

TITAN_EMBED_V2 = "amazon.titan-embed-text-v2"
COHERE_RERANK = "cohere.rerank"


def bedrock_region(region: Optional[str] = None) -> Optional[str]:
    """``region``, else ``AWS_REGION``.

    boto3 reads only ``AWS_DEFAULT_REGION`` (or a profile) by itself, so the
    ``AWS_REGION`` setting is passed to it explicitly. With neither, boto3's
    own default applies and fails loudly if there is none.
    """
    return region or os.getenv("AWS_REGION") or None


@lru_cache(maxsize=None)
def _client_for(region: Optional[str]) -> Any:
    # boto3 clients are thread-safe, so one client per region is shared.
    return boto3.client("bedrock-runtime", region_name=region, config=_RETRY_CONFIG)


def bedrock_runtime_client(region: Optional[str] = None) -> Any:
    """A Bedrock runtime client for ``region`` (default: ``AWS_REGION``)."""
    return _client_for(bedrock_region(region))


def _invoke(client: Any, model_id: str, body: dict) -> dict:
    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())


class BedrockEmbeddingClient:
    """Embeddings from Amazon Titan Text Embeddings V2 on Bedrock.

    Implements the same ``embed`` interface as the other embedding clients.
    Titan takes one text per request, so texts are sent in parallel.
    """

    def __init__(
        self,
        model_id: str,
        dimensions: Optional[int] = None,
        region: Optional[str] = None,
        max_workers: int = 8,
        client: Any = None,
    ):
        if not model_id.startswith(TITAN_EMBED_V2):
            raise ValueError(
                f"Unsupported Bedrock embedding model {model_id!r}: only Amazon "
                f"Titan Text Embeddings V2 ({TITAN_EMBED_V2}:0) is supported."
            )
        self.model_id = model_id
        self.dimensions = dimensions
        self.max_workers = max_workers
        self._client = client or bedrock_runtime_client(region)
        logger.info(
            "BedrockEmbeddingClient: model=%s, dimensions=%s", model_id, dimensions
        )

    def embed(
        self, documents: Iterable[str], batch_size: int = 0, **kwargs: Any
    ) -> Iterable[np.ndarray]:
        """Yield one embedding per text, in order."""
        texts = list(documents)
        if not texts:
            return
        _validate_texts(texts)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for vector in pool.map(self._embed_one, texts):
                yield np.array(vector, dtype=np.float32)

    def _embed_one(self, text: str) -> List[float]:
        body: dict = {"inputText": text, "normalize": True}
        if self.dimensions:
            body["dimensions"] = self.dimensions
        return _invoke(self._client, self.model_id, body)["embedding"]


def _validate_texts(texts: List[str]) -> None:
    bad = [i for i, t in enumerate(texts) if not isinstance(t, str) or not t.strip()]
    if bad:
        raise ValueError(
            f"BedrockEmbeddingClient received {len(bad)} empty or non-text "
            f"inputs, first at index {bad[0]}."
        )


def rerank_with_aws_bedrock(
    query: str,
    documents: List[str],
    model_id: str,
    region: Optional[str] = None,
    client: Any = None,
) -> List[float]:
    """Relevance scores for ``documents`` against ``query``, in input order.

    Supports Cohere Rerank on Bedrock. Rerank models are offered in only some
    regions, so ``region`` may differ from the deployment's own.
    """
    if not model_id.startswith(COHERE_RERANK):
        raise ValueError(
            f"Unsupported Bedrock rerank model {model_id!r}: only Cohere Rerank "
            f"({COHERE_RERANK}-v3-5:0) is supported."
        )
    if not documents:
        return []
    data = _invoke(
        client or bedrock_runtime_client(region),
        model_id,
        {
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "api_version": 2,
        },
    )
    return parse_cohere_rerank_scores(data, len(documents))


def parse_cohere_rerank_scores(data: dict, doc_count: int) -> List[float]:
    """Scores in input order from a Cohere rerank response."""
    scores: List[Optional[float]] = [None] * doc_count
    for result in data.get("results", []):
        index = result.get("index")
        if not isinstance(index, int) or not 0 <= index < doc_count:
            raise ValueError(f"Bedrock rerank returned an invalid index: {index!r}")
        scores[index] = float(result["relevance_score"])
    missing = [i for i, s in enumerate(scores) if s is None]
    if missing:
        raise ValueError(
            f"Bedrock rerank returned no score for {len(missing)} of "
            f"{doc_count} documents."
        )
    return [float(s) for s in scores if s is not None]
