"""Google Vertex AI reranker via Discovery Engine Ranking API."""

import logging
from typing import List, Optional

from google.cloud import discoveryengine_v1 as discoveryengine

from pipeline.utilities.google_vertex_client import _load_gcp_project_id

logger = logging.getLogger(__name__)


def rerank_with_google_vertex(
    query: str, documents: List[str], model_id: str
) -> List[float]:
    """Rerank documents using the Vertex AI Ranking API (Discovery Engine)."""
    project_id = _load_gcp_project_id()
    client = discoveryengine.RankServiceClient()
    ranking_config = client.ranking_config_path(
        project=project_id,
        location="global",
        ranking_config="default_ranking_config",
    )
    records = [
        discoveryengine.RankingRecord(id=str(i), content=doc)
        for i, doc in enumerate(documents)
    ]
    request = discoveryengine.RankRequest(
        ranking_config=ranking_config,
        model=model_id,
        top_n=len(documents),
        query=query,
        records=records,
    )
    response = client.rank(request=request)

    # Map scores back to original document order
    scores: List[Optional[float]] = [None] * len(documents)
    for record in response.records:
        idx = int(record.id)
        scores[idx] = record.score
    return [s if s is not None else 0.0 for s in scores]
