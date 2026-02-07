"""Taxonomy tagger implementation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastembed import TextEmbedding
from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

from pipeline.db import Database, PostgresClient
from pipeline.processors.tagging.tagger_base import BaseTagger
from pipeline.processors.tagging.tagger_llm import resolve_llm_config
from utils.llm_factory import get_llm

logger = logging.getLogger(__name__)

# Load Jinja2 templates for prompts
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)


class TaxonomyTagger(BaseTagger):
    """
    Labels documents/chunks based on configured taxonomies (e.g. SDGs).
    Uses LLM to determine applicability of taxonomy values.
    """

    name = "TaxonomyTagger"
    tag_field = (
        "sys_taxonomies"  # Primary field for storage, but returns dict of updates
    )

    def __init__(
        self,
        embedding_model: Optional[TextEmbedding] = None,
        config: Dict[str, Any] = None,
    ):
        super().__init__(embedding_model)
        self.config = config or {}
        self.taxonomies_config = self.config.get("taxonomies", {})
        self.llm_config = self.config.get("llm_model", {})
        self._database: Optional[Database] = None
        self._pg: Optional[PostgresClient] = None

        # Cache by document identifier
        # { doc_id: { "sys_taxonomies": {...}, "tags": { "tag_sdg": [...] } } }
        self._document_cache: Dict[str, Dict[str, Any]] = {}

    def set_db(self, database: Database) -> None:
        """Attach a database instance."""
        self._database = database
        self._pg = PostgresClient(database.data_source)

    def setup(self) -> None:
        """Initialize tagger resources. Validates that prompt templates exist."""
        missing = []
        for tax_key in self.taxonomies_config:
            for suffix in ("system", "user"):
                template_name = f"taxonomy_{tax_key}_{suffix}.j2"
                template_path = PROMPTS_DIR / template_name
                if not template_path.exists():
                    missing.append(template_name)
        if missing:
            raise FileNotFoundError(
                f"Missing taxonomy prompt templates: {', '.join(missing)}. "
                f"Expected in {PROMPTS_DIR}"
            )
        logger.info(
            "TaxonomyTagger initialized with taxonomies: %s",
            list(self.taxonomies_config.keys()),
        )

    def _get_document_identifier(self, document: Dict[str, Any]) -> Optional[str]:
        identifier = (
            document.get("id") or document.get("node_id") or document.get("doc_id")
        )
        return str(identifier) if identifier is not None else None

    def _build_taxonomy_prompt(
        self, taxonomy_key: str, taxonomy_config: Dict[str, Any], context_text: str
    ) -> Tuple[str, str]:
        """Build system and user prompts for a specific taxonomy using templates."""
        taxonomy_name = taxonomy_config.get("name", taxonomy_key)
        values = taxonomy_config.get("values", {})

        system_template = _jinja_env.get_template(f"taxonomy_{taxonomy_key}_system.j2")
        user_template = _jinja_env.get_template(f"taxonomy_{taxonomy_key}_user.j2")

        system_prompt = system_template.render(taxonomy_name=taxonomy_name).strip()

        user_prompt = user_template.render(
            context_text=context_text, values=values
        ).strip()

        return system_prompt, user_prompt

    def _clean_llm_content(self, content: str) -> str:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return content.strip()

    def _parse_llm_response(self, content: str) -> List[Dict[str, str]]:
        content = self._clean_llm_content(content)
        data = json.loads(content)

        # Expected format: [{"code": "...", "reason": "..."}]
        results = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "code" in item:
                    results.append(item)
                elif isinstance(item, str):
                    # Fallback for simple string list
                    results.append({"code": item, "reason": "No reason provided"})
            return results
        elif isinstance(data, dict):
            # Fallback for old {"code": true} format
            for k, v in data.items():
                if v:
                    results.append({"code": k, "reason": "No reason provided"})
            return results
        else:
            logger.warning("Unexpected JSON structure from LLM: %s", type(data))
            return []

    @traceable(run_type="llm", name="TaxonomyTagger")
    def _call_llm(
        self, system_prompt: str, user_prompt: str
    ) -> Optional[List[Dict[str, str]]]:
        """Call LLM and parse JSON response."""
        model_key, provider, temperature, max_tokens, inference_provider = (
            resolve_llm_config(self.config)
        )

        llm = get_llm(
            model=model_key,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
            inference_provider=inference_provider,
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = llm.invoke(messages)
            return self._parse_llm_response(str(response.content))
        except Exception as exc:
            logger.error("LLM call failed for taxonomy: %s", exc)
            return None

    def _process_taxonomy(
        self, tax_key: str, tax_config: Dict[str, Any], context_text: str
    ) -> List[Dict[str, str]]:
        """Process a single taxonomy. Returns list of dicts with code, name, reason."""
        system_prompt, user_prompt = self._build_taxonomy_prompt(
            tax_key, tax_config, context_text
        )

        results = self._call_llm(system_prompt, user_prompt)
        if not results:
            return []

        enriched_values = []
        defined_values = tax_config.get("values", {})

        for item in results:
            code = item.get("code")
            reason = item.get("reason", "No reason provided")
            if code and code in defined_values:
                name = defined_values[code].get("name", "")
                enriched_values.append({"code": code, "name": name, "reason": reason})
        return enriched_values

    def compute_document_tags(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Compute all taxonomy tags for a document. Returns cached if available."""
        doc_id = self._get_document_identifier(document)
        if not doc_id:
            return {}

        if doc_id in self._document_cache:
            return self._document_cache[doc_id]

        # Check existing tags in document if we want to skip re-processing?
        # For now, we assume if pipeline runs, we re-process.
        # But we could check existing sys_taxonomies.

        sys_taxonomies = {}
        tags_updates = {}

        summary = document.get("sys_full_summary")
        if not summary:
            # Cannot tag without full summary for document-level taxonomies
            self._document_cache[doc_id] = {}
            return {}

        for tax_key, tax_config in self.taxonomies_config.items():
            level = tax_config.get("level", "document")
            if level != "document":
                # Chunk level not fully supported in this pass or requires chunk text
                continue

            input_source = tax_config.get("input", "summary")
            context_text = (
                summary if input_source == "summary" else ""
            )  # Could handle full text later

            if not context_text:
                continue

            enriched_values = self._process_taxonomy(tax_key, tax_config, context_text)
            if enriched_values:
                sys_taxonomies[tax_key] = enriched_values
                # For backward compatibility with tag_sdg fields in Qdrant,
                # extract code-name strings
                tags_updates[f"tag_{tax_key}"] = [
                    f"{item['code']} - {item['name']}" if item["name"] else item["code"]
                    for item in enriched_values
                ]

        combined_result = {"sys_taxonomies": sys_taxonomies, **tags_updates}

        self._document_cache[doc_id] = combined_result
        return combined_result

    def tag_chunk(
        self, chunk: Dict[str, Any], document: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Apply taxonomy tags to a chunk.
        For document-level taxonomies, this returns the cached document tags.
        """
        if not self.taxonomies_config:
            return None

        doc_tags = self.compute_document_tags(document)

        # If we have chunk-level taxonomies, we would compute them here and merge.
        # But per requirements, we start with document-level.

        if not doc_tags:
            return None

        return doc_tags
