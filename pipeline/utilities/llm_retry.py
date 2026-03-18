"""Retry wrapper for transient LLM API errors (e.g. HuggingFace 500s)."""

import logging
import time
from typing import Any, List

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def invoke_with_retry(
    llm: Any, messages: List[Any], max_retries: int = MAX_RETRIES
) -> Any:
    """Call llm.invoke(messages) with exponential backoff on transient errors."""
    for attempt in range(max_retries):
        try:
            return llm.invoke(messages)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if attempt < max_retries - 1:
                wait = 2**attempt
                logger.warning(
                    "LLM invoke failed (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1,
                    max_retries,
                    wait,
                    exc,
                )
                time.sleep(wait)
            else:
                raise
