"""LLM helpers for tagger classification."""

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import HumanMessage, SystemMessage

from pipeline.db import SUPPORTED_LLMS
from pipeline.processors.tagging.tagger_constants import SECTION_TYPES
from utils.llm_factory import get_llm

logger = logging.getLogger(__name__)


def validate_llm_output(
    toc_entries: List[Dict[str, Any]],
    output_items: Any,
    locked_labels_by_index: Dict[int, str],
) -> Optional[Dict[int, str]]:
    """
    Validate LLM output strictly.
    Returns labels_by_index if valid, otherwise None.
    """
    # Relaxed check: We don't strictly require length match anymore,
    # as we will just use valid items found.

    if not isinstance(output_items, list):
        logger.warning("LLM output validation failed: Output is not a list.")
        return None

    seen_indices: set[int] = set()
    labels_by_index: Dict[int, str] = {}

    for i, item in enumerate(output_items):
        parsed = _parse_llm_item(item, i, len(toc_entries))
        if not parsed:
            continue
        index_value, label_value = parsed
        if index_value in seen_indices:
            logger.warning(
                "LLM output validation failed: Duplicate index %d.", index_value
            )
            continue
        seen_indices.add(index_value)
        labels_by_index[index_value] = _resolve_locked_label(
            index_value, label_value, locked_labels_by_index
        )

    return labels_by_index


def _parse_llm_item(
    item: Any, item_index: int, max_entries: int
) -> Optional[Tuple[int, str]]:
    """Parse and validate a single LLM output item."""
    if not isinstance(item, dict):
        logger.warning(
            "LLM output validation failed: Item %d is not a dict.", item_index
        )
        return None
    if "idx" not in item or "label" not in item:
        logger.warning(
            "LLM output validation failed: Item %d missing 'idx' or 'label'.",
            item_index,
        )
        return None
    try:
        index_value = int(item["idx"])
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning(
            "LLM output validation failed: Item %d 'idx' is not an int.", item_index
        )
        return None
    label_value = str(item["label"]).strip()
    if label_value not in SECTION_TYPES:
        logger.warning(
            "LLM output validation failed: Item %d has invalid label '%s'.",
            item_index,
            label_value,
        )
        return None
    if index_value < 0 or index_value >= max_entries:
        logger.warning(
            "LLM output validation failed: Item %d index %d out of range (0..%d).",
            item_index,
            index_value,
            max_entries - 1,
        )
        return None
    return index_value, label_value


def _resolve_locked_label(
    index_value: int,
    label_value: str,
    locked_labels_by_index: Dict[int, str],
) -> str:
    """Return the locked label when present, otherwise the LLM label."""
    locked_label = locked_labels_by_index.get(index_value)
    if locked_label is None:
        return label_value
    if label_value != locked_label:
        logger.info(
            "Overriding LLM label '%s' with locked label '%s' for index %d",
            label_value,
            locked_label,
            index_value,
        )
    return locked_label


def build_toc_items_payload(
    toc_entries: List[Dict[str, Any]], locked_labels_by_index: Dict[int, str]
) -> List[Dict[str, Any]]:
    """Build the TOC payload for LLM classification."""
    toc_items_payload: List[Dict[str, Any]] = []
    for entry in toc_entries:
        entry_index = entry["index"]
        toc_items_payload.append(
            {
                "idx": entry_index,
                "title": entry["title"],
                "level": entry["level"],
                "page": entry["page"],
                "locked_label": locked_labels_by_index.get(entry_index),
            }
        )
    return toc_items_payload


def build_toc_prompts(
    document_title: str,
    toc_items_payload: List[Dict[str, Any]],
    total_pages: Optional[int],
) -> Tuple[str, str]:
    """Render system and user prompts for TOC classification."""
    prompts_directory = Path(__file__).resolve().parents[3] / "prompts"
    jinja_environment = Environment(
        loader=FileSystemLoader(str(prompts_directory)), autoescape=True
    )
    system_template = jinja_environment.get_template("toc_classification_system.j2")
    user_template = jinja_environment.get_template("toc_classification_user.j2")

    system_prompt = system_template.render()
    user_prompt = user_template.render(
        doc_title=document_title,
        toc_items_json=json.dumps(toc_items_payload, ensure_ascii=False),
        total_pages=total_pages,
    )
    return system_prompt, user_prompt


def resolve_llm_config(
    llm_config: Dict[str, Any]
) -> Tuple[str | None, str, float, int, str | None]:
    """Resolve LLM configuration into model/provider parameters."""
    llm_model_config = llm_config.get("llm_model", {})
    if isinstance(llm_model_config, str):
        llm_model_config = {"model": llm_model_config}

    model_key = llm_model_config.get("model")
    temperature = llm_model_config.get("temperature", 0.0)
    max_tokens = llm_model_config.get("max_tokens", 4000)
    inference_provider = llm_model_config.get("inference_provider")

    provider = None
    if model_key and model_key in SUPPORTED_LLMS:
        provider = SUPPORTED_LLMS[model_key].get("provider", "huggingface")
        if not inference_provider:
            inference_provider = SUPPORTED_LLMS[model_key].get("inference_provider")
    elif model_key:
        matched_config = next(
            (cfg for cfg in SUPPORTED_LLMS.values() if cfg.get("model") == model_key),
            None,
        )
        if matched_config:
            provider = matched_config.get("provider", provider)
            if not inference_provider:
                inference_provider = matched_config.get("inference_provider")
        else:
            logger.warning(
                "Model key '%s' not found in supported_llms. "
                "Available keys: %s. "
                "Will attempt to use as model string (backward compatibility).",
                model_key,
                list(SUPPORTED_LLMS.keys()),
            )

    if not provider:
        provider = "huggingface"

    return model_key, provider, temperature, max_tokens, inference_provider


def invoke_and_parse_toc(
    llm: Any,
    system_prompt: str,
    user_prompt: str,
    toc_entries: List[Dict[str, Any]],
    locked_labels_by_index: Dict[int, str],
    additional_instruction: Optional[str],
) -> Optional[Dict[int, str]]:
    """Invoke the LLM and parse/validate the TOC classification output."""
    messages = [SystemMessage(content=system_prompt)]
    if additional_instruction:
        messages.append(SystemMessage(content=additional_instruction))
    messages.append(HumanMessage(content=user_prompt))

    response = llm.invoke(messages)
    response_text = str(response.content).strip()

    try:
        output_items = json.loads(response_text)
    except Exception:  # pylint: disable=broad-exception-caught
        start = response_text.find("[")
        end = response_text.rfind("]")
        if start >= 0 and end > start:
            try:
                output_items = json.loads(response_text[start : end + 1])
                print(output_items)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "LLM output parsing failed (fallback). "
                    "Exception: %s. Response text: %s",
                    exc,
                    response_text,
                )
                return None
        else:
            logger.warning(
                "LLM output parsing failed (no JSON array found). Response text: %s",
                response_text,
            )
            return None

    validated = validate_llm_output(toc_entries, output_items, locked_labels_by_index)
    if validated is None:
        logger.warning(
            "LLM output was valid JSON but failed semantic validation. "
            "Response text: %s",
            response_text,
        )
    return validated


_CHARS_PER_TOKEN = 2  # conservative estimate for structured/multilingual content


def _estimate_toc_prompt_overhead(
    document_title: str, total_pages: Optional[int]
) -> int:
    """Return character length of the TOC prompt with an empty TOC payload."""
    system_prompt, user_prompt = build_toc_prompts(
        document_title=document_title,
        toc_items_payload=[],
        total_pages=total_pages,
    )
    return len(system_prompt) + len(user_prompt)


def _split_toc_entries(
    toc_entries: List[Dict[str, Any]],
    locked_labels_by_index: Dict[int, str],
    max_payload_chars: int,
) -> List[List[Dict[str, Any]]]:
    """Split TOC entries into batches that fit within max_payload_chars.

    Each batch is sized so that its JSON-serialized payload stays under the
    character budget.  Splits are symmetric (equal-sized batches).
    """
    full_payload = build_toc_items_payload(toc_entries, locked_labels_by_index)
    full_chars = len(json.dumps(full_payload, ensure_ascii=False))

    if full_chars <= max_payload_chars:
        return [toc_entries]

    n_batches = math.ceil(full_chars / max_payload_chars)
    batch_size = math.ceil(len(toc_entries) / n_batches)

    batches = []
    for i in range(0, len(toc_entries), batch_size):
        batches.append(toc_entries[i : i + batch_size])

    logger.info(
        "TOC payload (%d chars) exceeds budget (%d chars); "
        "splitting %d entries into %d batches of ~%d",
        full_chars,
        max_payload_chars,
        len(toc_entries),
        len(batches),
        batch_size,
    )
    return batches


def call_llm_for_toc(
    document_title: str,
    toc_entries: List[Dict[str, Any]],
    locked_labels_by_index: Dict[int, str],
    llm_config: Dict[str, Any],
    total_pages: Optional[int] = None,
    retry_on_failure: bool = True,
) -> Dict[int, str]:
    """
    Call LLM to label TOC entries. Locked labels are included in the payload
    and must be preserved.
    If the LLM fails, returns a map that contains only locked labels
    (caller will fill by hierarchy).

    When the TOC is too large for the context window, entries are split into
    equal batches and each batch is classified independently.
    """
    model_key, provider, temperature, max_tokens, inference_provider = (
        resolve_llm_config(llm_config)
    )

    logger.info(
        "Tagger LLM config: model_key=%s, provider=%s (from supported_llms), "
        "temperature=%s, max_tokens=%s, inference_provider=%s",
        model_key,
        provider,
        temperature,
        max_tokens,
        inference_provider,
    )

    context_window = llm_config.get("context_window", 29000)
    available_input_tokens = context_window - max_tokens
    max_total_chars = int(available_input_tokens * _CHARS_PER_TOKEN)

    full_payload = build_toc_items_payload(toc_entries, locked_labels_by_index)
    sys_prompt, usr_prompt = build_toc_prompts(
        document_title=document_title,
        toc_items_payload=full_payload,
        total_pages=total_pages,
    )
    full_prompt_chars = len(sys_prompt) + len(usr_prompt)

    if full_prompt_chars > max_total_chars:
        payload_chars = len(json.dumps(full_payload, ensure_ascii=False))
        overhead_chars = full_prompt_chars - payload_chars
        max_payload_chars = max(max_total_chars - overhead_chars, 1)
    else:
        max_payload_chars = len(json.dumps(full_payload, ensure_ascii=False)) + 1

    batches = _split_toc_entries(
        toc_entries, locked_labels_by_index, max(max_payload_chars, 1)
    )

    llm = get_llm(
        model=model_key,
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
        inference_provider=inference_provider,
    )

    merged_labels: Dict[int, str] = {}

    for batch in batches:
        batch_payload = build_toc_items_payload(batch, locked_labels_by_index)
        system_prompt, user_prompt = build_toc_prompts(
            document_title=document_title,
            toc_items_payload=batch_payload,
            total_pages=total_pages,
        )

        labels_by_index = invoke_and_parse_toc(
            llm=llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            toc_entries=batch,
            locked_labels_by_index={
                k: v
                for k, v in locked_labels_by_index.items()
                if any(e["index"] == k for e in batch)
            },
            additional_instruction=None,
        )
        if labels_by_index:
            merged_labels.update(labels_by_index)
            continue

        if retry_on_failure:
            labels_by_index = invoke_and_parse_toc(
                llm=llm,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                toc_entries=batch,
                locked_labels_by_index={
                    k: v
                    for k, v in locked_labels_by_index.items()
                    if any(e["index"] == k for e in batch)
                },
                additional_instruction=(
                    "Return valid JSON only. No prose. No markdown. "
                    "Output must be a JSON array."
                ),
            )
            if labels_by_index:
                merged_labels.update(labels_by_index)

    if merged_labels:
        return merged_labels

    logger.warning(
        "LLM TOC classification failed to return any valid labels; "
        "falling back to locked labels only."
    )
    return dict(locked_labels_by_index)
