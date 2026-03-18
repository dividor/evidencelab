"""Azure Foundry reranker via Cohere API."""

import json
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def _get_azure_foundry_rerank_endpoint(config: Dict[str, Any], deployment: str) -> str:
    endpoint = (
        config.get("endpoint_url")
        or config.get("endpoint")
        or os.getenv("AZURE_FOUNDRY_ENDPOINT")
    )
    if not endpoint:
        raise ValueError("Azure Foundry rerank endpoint not configured.")
    azure_base = endpoint.rstrip("/")
    if "/providers/cohere/" in azure_base:
        return azure_base
    if "/openai/deployments/" in azure_base:
        azure_base = azure_base.split("/openai/deployments/")[0]
    if azure_base.endswith(".openai.azure.com"):
        azure_base = azure_base.replace(".openai.azure.com", ".services.ai.azure.com")
    return f"{azure_base}/providers/cohere/v2/rerank"


def _get_azure_foundry_api_key() -> str:
    api_key = os.getenv("AZURE_FOUNDRY_KEY")
    if not api_key:
        raise ValueError("AZURE_FOUNDRY_KEY is required for Azure Foundry reranking.")
    return api_key


def _scores_from_results(results: Any, doc_count: int) -> Optional[List[float]]:
    if not results:
        return None
    has_index = all(isinstance(r, dict) and "index" in r for r in results)
    if has_index:
        scores: List[Optional[float]] = [None] * doc_count
        for result in results:
            idx = result["index"]
            score = (
                result.get("relevance_score")
                or result.get("score")
                or result.get("relevanceScore")
            )
            if score is None or not isinstance(idx, int) or idx < 0 or idx >= doc_count:
                return None
            scores[idx] = score
        if any(s is None for s in scores):
            return None
        return [float(s) for s in scores]  # type: ignore[arg-type]
    scores_list = []
    for result in results:
        score = result.get("score")
        if score is None:
            score = result.get("relevance_score")
        if score is None:
            score = result.get("relevanceScore")
        if score is None:
            return None
        scores_list.append(score)
    if len(scores_list) != doc_count:
        return None
    return scores_list


def _scores_from_list(scores: Any) -> Optional[List[float]]:
    if not isinstance(scores, list):
        return None
    if not all(isinstance(score, (float, int)) for score in scores):
        return None
    return [float(score) for score in scores]


def _scores_from_data(data: Any, doc_count: int) -> Optional[List[float]]:
    if not isinstance(data, dict):
        return None
    scores = data.get("scores") or data.get("results") or data.get("data")
    if scores is None:
        return None
    if isinstance(scores, list) and all(isinstance(item, dict) for item in scores):
        return _scores_from_results(scores, doc_count)
    if isinstance(scores, list):
        parsed_scores = _scores_from_list(scores)
        if parsed_scores and len(parsed_scores) == doc_count:
            return parsed_scores
    return None


def parse_azure_rerank_response(response_text: Any, doc_count: int) -> List[float]:
    if isinstance(response_text, str):
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            raise ValueError("Azure rerank response is not valid JSON.")
    else:
        data = response_text

    scores = _scores_from_data(data, doc_count)
    if scores is None:
        raise ValueError("Azure rerank response missing scores.")
    return scores


def rerank_with_azure_foundry(
    query: str,
    documents: List[str],
    deployment: str,
    config: Dict[str, Any],
) -> List[float]:
    payload = {
        "model": deployment,
        "query": query,
        "documents": documents,
        "top_n": len(documents),
    }
    endpoint = _get_azure_foundry_rerank_endpoint(config, deployment)
    api_key = _get_azure_foundry_api_key()
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        response_text = response.read().decode("utf-8")
    return parse_azure_rerank_response(response_text, len(documents))
