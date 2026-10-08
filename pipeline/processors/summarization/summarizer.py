"""
summarizer.py - Document summarization processor.

Generates summaries using:
- LLM-based abstractive summarization (via HuggingFace Router API)
- Centroid-based extractive summarization using sentence embeddings
- Map-reduce strategy for large documents

NOTE: Document summarization currently uses direct HTTP requests to HuggingFace Router API.
To enable LangSmith tracing for this processor, it needs to be migrated to use LangChain.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import nltk
import numpy as np
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from nltk.tokenize import sent_tokenize
from sentence_transformers import util

from pipeline.db import SUPPORTED_LLMS
from pipeline.processors.base import BaseProcessor
from pipeline.processors.summarization.summary_text import (
    SUMMARY_USER_SET_FIELD,
    USE_CENTROID,
    SummaryTextMixin,
    count_prompt_tokens,
    default_summary_instructions,
    resolve_summary_mode,
)
from pipeline.utilities.embedding_service import EmbeddingService
from pipeline.utilities.llm_retry import invoke_with_retry
from pipeline.utilities.usage_recorder import UsageCollector, record_pipeline_usage
from utils import llm_factory
from utils.tracing import traceable

load_dotenv()

# Ensure NLTK data is available
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt", quiet=True)

try:
    nltk.data.find("tokenizers/punkt_tab")
except LookupError:
    nltk.download("punkt_tab", quiet=True)

logger = logging.getLogger(__name__)

# Model configuration
# Defaults for fallback if no shared model is provided
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
NUM_CENTROID_SENTENCES = 30


class SummarizeProcessor(SummaryTextMixin, BaseProcessor):
    """
    Document summarization processor.

    Generates abstractive and extractive summaries using:
    - LLM-based summarization via HuggingFace Router API
    - Centroid-based extractive summarization
    - Map-reduce for large documents
    """

    name = "SummarizeProcessor"
    stage_name = "summarize"

    def __init__(self, config: Dict[str, Any], data_source: Optional[str] = None):
        """
        Initialize summarizer configuration.

        Args:
            config: Strict configuration dictionary. Must contain:
                    - llm_model: Document model ID
                    - provider: LLM provider
                    - llm_workers: Concurrency limit (default 1)
                    - temperature: LLM temperature (default 0.1)
                    - max_tokens: Output token limit
            data_source: Datasource key, used to attribute recorded LLM
                token usage (see ``pipeline.utilities.usage_recorder``).
        """
        super().__init__()
        self.config = config
        self.data_source = data_source
        self._usage = UsageCollector()
        self._embedding_model = None
        self._hf_token: Optional[str] = None

        # Strict Config Parsing
        # Extract LLM model config (nested structure)
        llm_model_config = config.get("llm_model", {})
        if isinstance(llm_model_config, str):
            # Backward compatibility: if llm_model is a string, treat as model name
            llm_model_config = {"model": llm_model_config}

        self.model_key = llm_model_config.get("model")
        if not self.model_key:
            raise ValueError("SummarizeProcessor: 'llm_model.model' missing in config")

        # Get provider from supported_llms (not from config)
        if self.model_key in SUPPORTED_LLMS:
            self.provider = SUPPORTED_LLMS[self.model_key].get("provider")
            if not self.provider:
                raise ValueError(
                    f"SummarizeProcessor: provider not found in "
                    f"supported_llms for '{self.model_key}'"
                )
            # Also get inference_provider from supported_llms if not in config
            self.inference_provider = llm_model_config.get("inference_provider")
            if not self.inference_provider:
                self.inference_provider = SUPPORTED_LLMS[self.model_key].get(
                    "inference_provider"
                )
        else:
            # Try to match by "model" value in supported_llms
            matched_config = next(
                (
                    cfg
                    for cfg in SUPPORTED_LLMS.values()
                    if cfg.get("model") == self.model_key
                ),
                None,
            )
            if matched_config:
                self.provider = matched_config.get("provider", "huggingface")
                self.inference_provider = llm_model_config.get("inference_provider")
                if not self.inference_provider:
                    self.inference_provider = matched_config.get("inference_provider")
            else:
                # Backward compatibility: might be a model string
                logger.warning(
                    "Model key '%s' not found in supported_llms. "
                    "Using as model string (backward compatibility).",
                    self.model_key,
                )
                self.provider = llm_model_config.get("provider", "huggingface")
                self.inference_provider = llm_model_config.get("inference_provider")

        self.max_tokens = llm_model_config.get("max_tokens", 2000)
        self.temperature = llm_model_config.get("temperature", 0.1)

        # Resolve model key to actual model string for internal use
        # (get_llm will do this, but we need the actual string for _get_model_type)
        resolved_model, _, _ = llm_factory._resolve_model_key(self.model_key)
        self.model_name = resolved_model or self.model_key
        self.workers = config.get("llm_workers", 1)
        self.context_window = config.get("context_window", 29000)
        self.summary_mode = resolve_summary_mode(config)
        self.single_prompt_context_window = config.get("single_prompt_context_window")
        self.summary_instructions = default_summary_instructions()

        self._model_type = self._get_model_type()

    def _get_model_type(self) -> str:
        """Detect model type from configuration."""
        model_name = str(self.model_name).lower()
        if "bart" in model_name:
            return "bart"
        if "mistral" in model_name:
            return "mistral"
        if "llama" in model_name:
            return "llama"
        return "chat"

    def setup(self, embedding_service: Optional[EmbeddingService] = None) -> None:
        """
        Load embedding model via EmbeddingService and get LLM token.

        Args:
            embedding_service: Central embedding service for obtaining
                model clients.
        """
        logger.info("Initializing %s...", self.name)

        # Resolve dense_model from config
        dense_model_name = self.config.get("dense_model")
        if not dense_model_name:
            raise ValueError(
                "SummarizeProcessor: 'dense_model' missing in summarize config. "
                "Add it to datasources.<name>.pipeline.summarize in config.json."
            )

        if embedding_service is not None:
            logger.info(
                "Loading embedding model '%s' via EmbeddingService", dense_model_name
            )
            self._embedding_model = embedding_service.get_model(dense_model_name)
        else:
            raise ValueError(
                "SummarizeProcessor: embedding_service is required. "
                "Ensure the worker provides an EmbeddingService instance."
            )

        # HuggingFace token is only required when the LLM provider is
        # HuggingFace. Other providers (Azure Foundry, Google Vertex) authenticate
        # with their own credentials, so demanding an HF token here would block
        # them needlessly (the token is otherwise unused).
        self._hf_token = os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN")
        if self.provider == "huggingface" and not self._hf_token:
            raise ValueError(
                "HUGGINGFACE_API_KEY or HF_TOKEN not found in environment. "
                "Get your token at https://huggingface.co/settings/tokens"
            )

        logger.info("✓ Summarizer ready (model: %s)", self.model_name)
        super().setup()

    def process_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Summarize a single document.

        Args:
            doc: Document dict with 'id', 'parsed_folder', 'title' fields

        Returns:
            Dict with success status and updates for database
        """
        self.ensure_setup()

        parsed_folder = doc.get("sys_parsed_folder")
        title = doc.get("map_title", "Unknown")

        kept = self._keep_app_summary(doc, title)
        if kept is not None:
            return kept

        if not parsed_folder or not os.path.exists(parsed_folder):
            return self._build_failure(
                doc,
                "Parsed folder not found",
                f"Parsed folder not found: {parsed_folder}",
            )

        logger.info("Summarizing: %s", title)

        # No reset here: record_pipeline_usage in the finally below drains the
        # collector, and an explicit reset would drop other documents'
        # in-flight counts when scripts share one processor across threads.
        try:
            markdown_path = self._find_markdown_file(parsed_folder)
            if not markdown_path:
                return self._build_failure(
                    doc, "No markdown file", "No markdown file in parsed folder"
                )

            content = self._load_markdown(markdown_path)
            if not content:
                return self._build_failure(
                    doc, "Empty markdown", "Could not load markdown content"
                )

            return self._summarize_content(doc, content, markdown_path, title)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Exception summarizing %s: %s", title, e)
            return self._build_failure(doc, str(e), str(e))
        finally:
            # Record whatever the doc consumed — including partial usage from
            # a failed map-reduce — as one 'pipeline' activity row per model.
            record_pipeline_usage(
                self._usage,
                stage=self.stage_name,
                data_source=self.data_source,
                doc_id=str(doc.get("id") or ""),
                query=f"{self.stage_name}: {title}",
            )

    def _keep_app_summary(
        self, doc: Dict[str, Any], title: str
    ) -> Optional[Dict[str, Any]]:
        """Keep a summary written or edited in the app.

        Such a summary is marked ``sys_summary_user_set``; reprocessing keeps
        it unless the reprocess request cleared the mark to replace it.
        """
        sys_data = doc.get("sys_data") or {}
        summary = doc.get("sys_full_summary")
        if not (sys_data.get(SUMMARY_USER_SET_FIELD) and summary):
            return None
        logger.info("Keeping the summary set in the app for: %s", title)
        method = sys_data.get("sys_summarization_method") or "ui_edited"
        return self._build_success(doc, summary, method)

    def _find_markdown_file(self, parsed_folder: str) -> Optional[str]:
        markdown_files = list(Path(parsed_folder).glob("*.md"))
        return str(markdown_files[0]) if markdown_files else None

    def _build_failure(
        self, doc: Dict[str, Any], message: str, error: str
    ) -> Dict[str, Any]:
        stage_updates = self.build_stage_updates(doc, success=False, error=message)
        return {
            "success": False,
            "updates": {
                "sys_status": "summarize_failed",
                "sys_error_message": message,
                **stage_updates,
            },
            "error": error,
        }

    def _build_success(
        self, doc: Dict[str, Any], summary: str, method: str
    ) -> Dict[str, Any]:
        stage_updates = self.build_stage_updates(doc, success=True, method=method)
        return {
            "success": True,
            "updates": {
                "sys_status": "summarized",
                "sys_full_summary": summary,
                "sys_summarization_method": method,
                **stage_updates,
            },
            "error": None,
        }

    def _summarize_content(
        self, doc: Dict[str, Any], content: str, markdown_path: str, title: str
    ) -> Dict[str, Any]:
        logger.info("  Generating LLM summary...")
        llm_summary, _ = self._llm_summary(content)
        if llm_summary and llm_summary != USE_CENTROID:
            self._save_summary(markdown_path, llm_summary, "llm_summary")
            return self._build_success(doc, llm_summary, "llm_summary")
        if llm_summary == USE_CENTROID:
            return self._summarize_with_centroid(doc, content, markdown_path, title)
        return self._build_failure(
            doc, "LLM summary failed", "LLM summary returned None"
        )

    def _summarize_with_centroid(
        self, doc: Dict[str, Any], content: str, markdown_path: str, title: str
    ) -> Dict[str, Any]:
        logger.info("  Content too large, using centroid fallback...")
        centroid = self._centroid_summary(content, title)
        if not centroid:
            return self._build_failure(
                doc, "LLM summary failed", "LLM summary returned None"
            )

        llm_summary, _ = self._llm_summary(centroid)
        if llm_summary and llm_summary != USE_CENTROID:
            self._save_summary(markdown_path, llm_summary, "llm_summary")
            return self._build_success(doc, llm_summary, "llm_on_centroid")

        self._save_summary(markdown_path, centroid, "centroid")
        return self._build_success(doc, centroid, "centroid_only")

    def _load_markdown(self, filepath: str) -> str:
        """Load and clean markdown content."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Remove images, comments, page separators
        content = re.sub(r"!\[.*?\]\(.*?\)", "", content)
        content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
        content = re.sub(r"------- Page \d+ -------", "", content)
        content = re.sub(r"------- Page Break -------", "", content)

        return content.strip()

    def _save_summary(
        self, markdown_path: str, content: str, suffix: str
    ) -> Optional[str]:
        """Save summary to file in the document folder."""
        try:
            md_path = Path(markdown_path)
            parent_dir = md_path.parent
            content_path = parent_dir / f"{suffix}.txt"

            with open(content_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info("  ✓ Saved %s to %s", suffix, content_path)
            return str(content_path)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to save summary: %s", e)
            return None

    def _centroid_summary(
        self, content: str, title: Optional[str] = None
    ) -> Optional[str]:
        """Generate extractive summary using centroid-based approach."""
        sentences = self._tokenize_sentences(content)

        if not sentences:
            return None

        logger.info("  Processing %s sentences...", len(sentences))

        embeddings = self._build_sentence_embeddings(sentences)
        if embeddings is None:
            return None

        # Calculate centroid
        centroid = np.mean(embeddings, axis=0)

        # Get most similar sentences
        similarities = util.cos_sim(centroid, embeddings)[0]
        top_indices_raw = similarities.argsort(descending=True)[:NUM_CENTROID_SENTENCES]
        top_indices = sorted(top_indices_raw)  # Keep original order

        # Join sentences
        summary_sentences = [sentences[i] for i in top_indices]
        cleaned = [" ".join(s.split()) for s in summary_sentences]
        summary = "\n\n---\n\n".join(cleaned)

        if title:
            summary = f"# {title}\n\n{summary}"

        return summary

    def _build_sentence_embeddings(self, sentences: List[str]) -> Optional[np.ndarray]:
        try:
            inputs = self._prepare_embedding_inputs(sentences)
            if self._embedding_model is None:
                raise ValueError("Embedding model not initialized")

            gen = self._embedding_model.embed(inputs, batch_size=32)
            return np.array(list(gen))
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to generate embeddings: %s", e)
            return None

    def _prepare_embedding_inputs(self, sentences: List[str]) -> List[str]:
        dense_model_name = self.config.get("dense_model", "")
        if "e5" in dense_model_name.lower():
            return [f"passage: {sentence}" for sentence in sentences]
        return sentences

    def _tokenize_sentences(self, text: str) -> List[str]:
        """Tokenize text into sentences."""
        sentences = sent_tokenize(text)

        filtered = []
        for s in sentences:
            if len(s.split()) <= 5:
                continue
            if "|" in s or "---" in s:
                continue
            filtered.append(s)

        return filtered

    def _build_llm(self, model: str, include_inference: bool) -> Any:
        return llm_factory.get_llm(
            model=model,
            provider=self.provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            inference_provider=self.inference_provider if include_inference else None,
        )

    def _count_prompt_tokens(self, prompt: str) -> int:
        # A single prompt is sent like a single pass: model key + inference provider.
        return count_prompt_tokens(self._build_llm(self.model_key, True), prompt)

    @traceable(name="Summarization")
    def _invoke_llm(self, prompt: str, model: str, include_inference: bool) -> str:
        llm = self._build_llm(model, include_inference)
        response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
        # Attribute usage to the configured model key (the pricing-table key),
        # regardless of whether the call resolved it to a provider model id.
        self._usage.add_response(response, self.model_key)
        if hasattr(response, "content"):
            return response.content.strip()
        return str(response).strip()

    def teardown(self) -> None:
        """Release summarizer resources."""
        self._embedding_model = None
        super().teardown()
