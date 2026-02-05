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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import nltk
import numpy as np
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import HumanMessage
from langsmith import traceable
from nltk.tokenize import sent_tokenize
from sentence_transformers import SentenceTransformer, util

from pipeline.db import SUPPORTED_LLMS
from pipeline.processors.base import BaseProcessor
from pipeline.utilities.logging_utils import _log_context
from utils import llm_factory
from utils.langsmith_util import setup_langsmith_tracing

load_dotenv()

# Setup LangSmith tracing
setup_langsmith_tracing()

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

# Load Jinja2 templates for prompts
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)
_reduction_template = _jinja_env.get_template("summary_reduction.j2")
_final_template = _jinja_env.get_template("summary_final.j2")


def _clean_markdown(text: str) -> str:
    """Clean markdown formatting issues in LLM-generated text."""
    if not text:
        return text
    return re.sub(
        r"^(#{1,6})\s*\*\*\s*(.+?)\s*\*\*\s*$", r"\1 \2", text, flags=re.MULTILINE
    )


class SummarizeProcessor(BaseProcessor):
    """
    Document summarization processor.

    Generates abstractive and extractive summaries using:
    - LLM-based summarization via HuggingFace Router API
    - Centroid-based extractive summarization
    - Map-reduce for large documents
    """

    name = "SummarizeProcessor"
    stage_name = "summarize"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize summarizer configuration.

        Args:
            config: Strict configuration dictionary. Must contain:
                    - llm_model: Document model ID
                    - provider: LLM provider
                    - llm_workers: Concurrency limit (default 1)
                    - temperature: LLM temperature (default 0.1)
                    - max_tokens: Output token limit
        """
        super().__init__()
        self.config = config
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

    def setup(self, embedding_model=None) -> None:
        """
        Load embedding model and get LLM token.

        Args:
            embedding_model: Optional shared embedding model
                             (SentenceTransformer, fastembed, or RemoteEmbeddingClient)
        """
        logger.info("Initializing %s...", self.name)

        # Load embedding model
        if embedding_model:
            logger.info("Using shared embedding model")
            self._embedding_model = embedding_model
        else:
            # Fallback to local loading
            model_name = os.getenv("DENSE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
            logger.info("Loading local embedding model (%s)...", model_name)
            # We use SentenceTransformer for local fallback to maintain compatibility
            # unless we decided to switch to fastembed entirely, but for now this is safest.
            self._embedding_model = SentenceTransformer(model_name)

        # Get HuggingFace token
        self._hf_token = os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN")
        if not self._hf_token:
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

        if not parsed_folder or not os.path.exists(parsed_folder):
            return self._build_failure(
                doc,
                "Parsed folder not found",
                f"Parsed folder not found: {parsed_folder}",
            )

        logger.info("Summarizing: %s", title)

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
        if llm_summary and llm_summary != "USE_CENTROID":
            self._save_summary(markdown_path, llm_summary, "llm_summary")
            return self._build_success(doc, llm_summary, "llm_summary")
        if llm_summary == "USE_CENTROID":
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
        if llm_summary and llm_summary != "USE_CENTROID":
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
        top_indices = similarities.argsort(descending=True)[:NUM_CENTROID_SENTENCES]
        top_indices = sorted(top_indices)  # Keep original order

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

            if hasattr(self._embedding_model, "embed"):
                gen = self._embedding_model.embed(inputs, batch_size=32)
                return np.array(list(gen))

            return self._embedding_model.encode(inputs, show_progress_bar=False)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to generate embeddings: %s", e)
            return None

    def _prepare_embedding_inputs(self, sentences: List[str]) -> List[str]:
        is_e5 = (
            "e5" in os.getenv("DENSE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).lower()
        )
        if not is_e5:
            return sentences
        return [f"passage: {sentence}" for sentence in sentences]

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

    def _llm_summary(self, content: str) -> Tuple[Optional[str], Optional[str]]:
        """Generate summary using LLM via HuggingFace Router API."""
        if not content:
            return None, None
        cleaned = self._clean_llm_input(content)
        if not cleaned:
            return None, None

        logger.info("  Input: %s characters", len(cleaned))

        try:
            max_chars = self.context_window
            effective_max = self._effective_max_chars(max_chars)
            if len(cleaned) <= effective_max:
                return self._single_pass_summary(cleaned)
            return self._map_reduce_summary(cleaned, max_chars, effective_max)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("  ✗ LLM summarization failed: %s", e)
            raise RuntimeError(f"LLM API call failed: {e}") from e

    def _clean_llm_input(self, content: str) -> str:
        cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", content)
        cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"------- Page \d+ -------", "", cleaned)
        cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned)
        cleaned = re.sub(r" +", " ", cleaned).strip()
        return cleaned

    def _effective_max_chars(self, max_chars: int) -> int:
        prompt_overhead = len(_reduction_template.render(document_text="")) + 100
        return max_chars - prompt_overhead

    @traceable(name="Summarization")
    def _invoke_llm(self, prompt: str, model: str, include_inference: bool) -> str:
        llm = llm_factory.get_llm(
            model=model,
            provider=self.provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            inference_provider=self.inference_provider if include_inference else None,
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        if hasattr(response, "content"):
            return response.content.strip()
        return str(response).strip()

    def _single_pass_summary(self, cleaned: str) -> Tuple[str, Optional[str]]:
        logger.info("  Single-pass summarization")
        prompt = _reduction_template.render(document_text=cleaned)
        logger.info("=" * 80)
        logger.info("LLM Summary Request (Single-pass)")
        logger.info("=" * 80)
        logger.info("PROMPT:")
        logger.info(prompt[:500] + "..." if len(prompt) > 500 else prompt)
        logger.info("=" * 80)
        summary = self._invoke_llm(prompt, self.model_key, include_inference=True)
        summary = _clean_markdown(summary)
        logger.info("LLM RESPONSE:")
        logger.info(summary[:500] + "..." if len(summary) > 500 else summary)
        logger.info("=" * 80)
        if not summary or len(summary) < 50:
            raise ValueError(f"Response too short: {len(summary)} chars")
        logger.info("  ✓ Summary: %s characters", len(summary))
        return summary, None

    def _map_reduce_summary(
        self,
        cleaned: str,
        max_chars: int,
        effective_max: int,
        recursion_depth: int = 0,
    ) -> Tuple[str, Optional[str]]:
        """
        Execute map-reduce summarization with recursion support.

        Args:
            cleaned: Text to summarize
            max_chars: Maximum characters allowed in context window
            effective_max: Effective max chars after prompt overhead
            recursion_depth: Current recursion depth (default 0)

        Returns:
            Tuple[str, Optional[str]]: (final_summary, intermediate_summaries)
        """
        logger.info("  Using map-reduce strategy (depth %s)", recursion_depth)

        MAX_RECURSION_DEPTH = 3
        if recursion_depth > MAX_RECURSION_DEPTH:
            logger.warning(
                "  Max recursion depth (%s) reached. Returning combined summaries.",
                MAX_RECURSION_DEPTH,
            )
            return cleaned, cleaned  # Fallback to returning what we have

        chunks = self._split_chunks(cleaned, effective_max)
        logger.info("  Split into %s chunks", len(chunks))

        # If splitting didn't reduce the number of chunks (e.g. 1 massive chunk),
        # prevent infinite recursion if we can't split it further meaningfuly.
        # But here _split_chunks uses strict sizing, so it should always split.

        if len(chunks) > 50:  # Increased safety limit
            logger.warning("  Too many chunks (%s) - will use centroid", len(chunks))
            return "USE_CENTROID", None

        current_doc_id = getattr(_log_context, "doc_id", "N/A")
        chunk_summaries = self._summarize_chunks(chunks, current_doc_id)

        combined = "\n\n".join(chunk_summaries)
        logger.info("  Combined: %s characters", len(combined))

        # If combined is still too large, RECURSE
        if len(combined) > max_chars:
            logger.info(
                "  Combined summaries (%s chars) > max window (%s). Recursing...",
                len(combined),
                max_chars,
            )
            return self._map_reduce_summary(
                combined, max_chars, effective_max, recursion_depth + 1
            )

        prompt = _final_template.render(map_summaries=combined)
        logger.info("=" * 80)
        logger.info("LLM Summary Request (Final Reduction, Depth %s)", recursion_depth)
        logger.info("=" * 80)
        logger.info("FINAL REDUCTION PROMPT:")
        logger.info(prompt[:500] + "..." if len(prompt) > 500 else prompt)
        logger.info("=" * 80)
        final = self._invoke_llm(prompt, self.model_name, include_inference=False)
        final = _clean_markdown(final)
        logger.info("LLM RESPONSE:")
        logger.info(final[:500] + "..." if len(final) > 500 else final)
        logger.info("=" * 80)
        logger.info("  ✓ Final summary: %s characters", len(final))
        return final, combined

    def _split_chunks(self, text: str, effective_max: int) -> List[str]:
        chunks = []
        start = 0
        overlap = self.config.get("chunk_overlap", 800)
        while start < len(text):
            end = min(start + effective_max, len(text))
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - overlap
        return chunks

    def _summarize_chunks(self, chunks: List[str], current_doc_id: str) -> List[str]:
        if self.workers == 1:
            logger.info("  Processing chunks sequentially (workers=1)")
            return [
                self._summarize_chunk(idx, chunk, len(chunks), current_doc_id)[1]
                for idx, chunk in enumerate(chunks, 1)
            ]

        logger.info(
            "  Processing %s chunks with %s parallel workers",
            len(chunks),
            self.workers,
        )
        chunk_results = {}
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(
                    self._summarize_chunk, i, chunk, len(chunks), current_doc_id
                ): i
                for i, chunk in enumerate(chunks, 1)
            }
            for future in as_completed(futures):
                idx, summary = future.result()
                chunk_results[idx] = summary
        return [chunk_results[idx] for idx in sorted(chunk_results.keys())]

    def _summarize_chunk(
        self, idx: int, chunk: str, total: int, doc_id: str
    ) -> Tuple[int, str]:
        _log_context.doc_id = doc_id
        logger.info("    Summarizing Chunk %s/%s...", idx, total)
        prompt = _reduction_template.render(document_text=chunk)
        if idx == 1:
            logger.info("=" * 80)
            logger.info("LLM Summary Request (Map-Reduce, Chunk %s/%s)", idx, total)
            logger.info("=" * 80)
            logger.info("CHUNK REDUCTION PROMPT:")
            logger.info(prompt[:500] + "..." if len(prompt) > 500 else prompt)
            logger.info("=" * 80)
        summary = self._invoke_llm(prompt, self.model_name, include_inference=False)
        return idx, summary

    def teardown(self) -> None:
        """Release summarizer resources."""
        self._embedding_model = None
        super().teardown()
