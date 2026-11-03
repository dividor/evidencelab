"""Amazon Bedrock as a model provider: embeddings, reranking and the LLM.

The Bedrock runtime client is replaced by a fake that records requests and
answers like Bedrock, so these tests check the request bodies and the parsing
without AWS credentials.
"""

import io
import json
from decimal import Decimal

import numpy as np
import pytest

from pipeline.db import DB_VECTORS, SUPPORTED_LLMS, SUPPORTED_RERANK_MODELS
from pipeline.utilities import aws_bedrock_client as bedrock
from pipeline.utilities.embedding_service import EmbeddingService

pytestmark = pytest.mark.unit


class FakeBedrock:
    """Answers invoke_model like Bedrock, recording each request."""

    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    def invoke_model(self, modelId, body, contentType, accept):
        request = json.loads(body)
        self.requests.append({"model": modelId, "body": request})
        return {"body": io.BytesIO(json.dumps(self.reply(request)).encode())}


def titan_reply(request):
    # A vector derived from the text, so the order of results can be checked.
    return {"embedding": [float(len(request["inputText"])), 0.0, 1.0]}


class TestBedrockEmbeddingClient:
    def test_embed_when_texts_given_then_returns_vectors_in_order(self):
        fake = FakeBedrock(titan_reply)
        client = bedrock.BedrockEmbeddingClient(
            "amazon.titan-embed-text-v2:0", dimensions=1024, client=fake
        )

        vectors = list(client.embed(["a", "abcd", "ab"]))

        assert [v[0] for v in vectors] == [1.0, 4.0, 2.0]
        assert all(isinstance(v, np.ndarray) and v.dtype == np.float32 for v in vectors)

    def test_embed_when_called_then_asks_titan_for_normalised_vectors_of_its_size(
        self,
    ):
        fake = FakeBedrock(titan_reply)
        client = bedrock.BedrockEmbeddingClient(
            "amazon.titan-embed-text-v2:0", dimensions=1024, client=fake
        )

        list(client.embed(["fraud"]))

        assert fake.requests == [
            {
                "model": "amazon.titan-embed-text-v2:0",
                "body": {"inputText": "fraud", "normalize": True, "dimensions": 1024},
            }
        ]

    def test_embed_when_text_empty_then_raises(self):
        client = bedrock.BedrockEmbeddingClient(
            "amazon.titan-embed-text-v2:0", client=FakeBedrock(titan_reply)
        )
        with pytest.raises(ValueError, match="empty or non-text"):
            list(client.embed(["ok", "  "]))

    def test_init_when_model_is_not_titan_v2_then_raises(self):
        with pytest.raises(ValueError, match="Titan Text Embeddings V2"):
            bedrock.BedrockEmbeddingClient(
                "cohere.embed-v4:0", client=FakeBedrock(titan_reply)
            )


class TestBedrockRerank:
    def test_rerank_when_called_then_returns_scores_in_input_order(self):
        fake = FakeBedrock(
            lambda req: {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ]
            }
        )

        scores = bedrock.rerank_with_aws_bedrock(
            "procurement fraud",
            ["weather", "bid rigging"],
            "cohere.rerank-v3-5:0",
            client=fake,
        )

        assert scores == [0.1, 0.9]
        assert fake.requests[0]["body"] == {
            "query": "procurement fraud",
            "documents": ["weather", "bid rigging"],
            "top_n": 2,
            "api_version": 2,
        }

    def test_parse_when_a_score_is_missing_then_raises(self):
        with pytest.raises(ValueError, match="no score for 1 of 2"):
            bedrock.parse_cohere_rerank_scores(
                {"results": [{"index": 0, "relevance_score": 0.5}]}, 2
            )

    def test_parse_when_index_out_of_range_then_raises(self):
        with pytest.raises(ValueError, match="invalid index"):
            bedrock.parse_cohere_rerank_scores(
                {"results": [{"index": 5, "relevance_score": 0.5}]}, 2
            )

    def test_rerank_when_model_is_not_cohere_then_raises(self):
        with pytest.raises(ValueError, match="Cohere Rerank"):
            bedrock.rerank_with_aws_bedrock(
                "q", ["d"], "amazon.rerank-v1:0", client=FakeBedrock(dict)
            )

    def test_rerank_when_no_documents_then_returns_empty_without_calling(self):
        fake = FakeBedrock(dict)
        assert (
            bedrock.rerank_with_aws_bedrock(
                "q", [], "cohere.rerank-v3-5:0", client=fake
            )
            == []
        )
        assert fake.requests == []


class TestRegion:
    def test_region_when_aws_region_set_then_used(self, monkeypatch):
        # boto3 itself ignores AWS_REGION, which left clients with no region.
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        assert bedrock.bedrock_region() == "us-east-2"

    def test_region_when_given_then_overrides_aws_region(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        assert bedrock.bedrock_region("us-west-2") == "us-west-2"

    def test_client_when_aws_region_set_then_targets_that_region(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        assert bedrock.bedrock_runtime_client().meta.region_name == "us-east-2"


class TestWiring:
    def test_embedding_service_when_source_aws_bedrock_then_uses_bedrock_client(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            bedrock,
            "bedrock_runtime_client",
            lambda region=None: FakeBedrock(titan_reply),
        )
        client = EmbeddingService().get_model("aws_titan_v2")

        assert isinstance(client, bedrock.BedrockEmbeddingClient)
        assert client.dimensions == DB_VECTORS["aws_titan_v2"]["size"] == 1024

    def test_search_reranker_when_provider_aws_bedrock_then_calls_its_region(
        self, monkeypatch
    ):
        from ui.backend.services import search_models

        calls = []
        monkeypatch.setattr(
            search_models,
            "rerank_with_aws_bedrock",
            lambda **kw: calls.append(kw) or [0.3],
        )
        config = SUPPORTED_RERANK_MODELS["cohere-rerank-3.5-bedrock"]

        scores = search_models._compute_rerank_scores(
            "q", ["d"], None, config, "cohere-rerank-3.5-bedrock", None, None
        )

        assert scores == [0.3]
        assert calls[0]["model_id"] == "cohere.rerank-v3-5:0"
        assert calls[0]["region"] == "us-west-2"

    def test_llm_factory_when_provider_aws_bedrock_then_builds_converse_model(
        self, monkeypatch
    ):
        from langchain_aws import ChatBedrockConverse

        from utils import llm_factory

        monkeypatch.setenv("AWS_REGION", "us-east-2")
        llm = llm_factory._create_llm_for_provider(
            "aws_bedrock", "us.amazon.nova-2-lite-v1:0", 0.2, 2000, None
        )

        assert isinstance(llm, ChatBedrockConverse)
        assert llm.model_id == "us.amazon.nova-2-lite-v1:0"
        assert llm.max_tokens == 2000
        assert llm.region_name == "us-east-2"

    def test_config_when_loaded_then_aws_bedrock_combo_names_bedrock_models(self):
        with open("config.json") as f:
            config = json.load(f)
        combo = config["ui_model_combos"]["AWS Bedrock"]

        assert DB_VECTORS[combo["embedding_model"]]["source"] == "aws_bedrock"
        assert (
            SUPPORTED_LLMS[combo["assistant_model"]["model"]]["provider"]
            == "aws_bedrock"
        )
        assert (
            SUPPORTED_RERANK_MODELS[combo["reranker_model"]]["provider"]
            == "aws_bedrock"
        )

    def test_costs_when_nova_2_lite_then_uses_bedrock_prices(self):
        from ui.backend.utils.llm_costs import compute_cost

        assert compute_cost("nova-2-lite", 1000, 1000) == Decimal("0.003080")


class TestDemo:
    def test_demo_combo_when_aws_bedrock_then_asks_for_aws_credentials(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_demo", "scripts/demo/run_demo.py"
        )
        run_demo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(run_demo)
        combo = next(
            c for c in run_demo.PROVIDER_COMBOS if c["llm_provider"] == "aws_bedrock"
        )

        assert combo["name"] == "AWS Bedrock"
        assert combo["required_env"] == [
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_REGION",
        ]
