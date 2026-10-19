"""Retry wrapper for transient LLM API errors (provider 429s, 5xxs, timeouts).

Rate-limited endpoints are the common case: Azure OpenAI returns HTTP 429 with a
``Retry-After`` header once a deployment's tokens-per-minute ceiling is reached.
A short, fixed backoff turns that *transient* condition into a *permanent*
document failure, so this module waits for as long as the provider asks, and
otherwise backs off exponentially with jitter.

Defaults are deliberately modest because this is also used on the live API path
(``ui/backend/services/document_summary.py``), where a request must not hang for
minutes. Bulk ingestion raises the budget through the environment variables
below. Every setting has a working default, so nothing needs to be configured.
"""

import logging
import os
import random
import time
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Number of attempts in total, not retries after the first try.
DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY_SECONDS = 1.0
DEFAULT_MAX_DELAY_SECONDS = 30.0

# Retained for backwards compatibility with callers importing the old constant.
MAX_RETRIES = DEFAULT_MAX_RETRIES


def _env_number(name: str, default: float, cast: Any) -> Any:
    """Read a numeric setting, falling back to ``default`` with a loud warning."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return cast(default)
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return cast(default)
    if value <= 0:
        logger.warning("%s=%r must be positive; using default %s", name, raw, default)
        return cast(default)
    return value


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    """Return the provider's requested wait, if it sent one.

    Handles both ``Retry-After`` (seconds) and ``retry-after-ms``. An HTTP-date
    ``Retry-After`` is not parsed; the caller then uses exponential backoff.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    for key, divisor in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        raw = headers.get(key)
        if raw is None or raw == "":
            continue
        try:
            return max(0.0, float(raw) / divisor)
        except (TypeError, ValueError):
            continue
    return None


def _delay_for_attempt(
    attempt: int, base: float, cap: float, retry_after: Optional[float]
) -> float:
    """Seconds to wait before the next attempt (1-based ``attempt``)."""
    if retry_after is not None:
        return min(retry_after, cap)
    window = min(cap, base * (2 ** (attempt - 1)))
    # Equal jitter: keeps a useful minimum wait while de-synchronising workers,
    # which matters when many pipeline workers are throttled at the same moment.
    half = window / 2.0
    return half + random.uniform(0.0, half)


def invoke_with_retry(
    llm: Any, messages: List[Any], max_retries: Optional[int] = None
) -> Any:
    """Call ``llm.invoke(messages)``, retrying transient failures.

    Raises the provider's own exception once the attempt budget is exhausted;
    failures are never swallowed.
    """
    attempts = (
        max_retries
        if max_retries is not None
        else _env_number("LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES, int)
    )
    attempts = max(1, attempts)
    base = _env_number(
        "LLM_RETRY_BASE_DELAY_SECONDS", DEFAULT_BASE_DELAY_SECONDS, float
    )
    cap = _env_number("LLM_RETRY_MAX_DELAY_SECONDS", DEFAULT_MAX_DELAY_SECONDS, float)

    attempt = 0
    while True:
        try:
            return llm.invoke(messages)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            attempt += 1
            if attempt >= attempts:
                logger.error(
                    "LLM invoke failed after %d attempt(s), giving up: %s",
                    attempts,
                    exc,
                )
                raise
            retry_after = _retry_after_seconds(exc)
            delay = _delay_for_attempt(attempt, base, cap, retry_after)
            logger.warning(
                "LLM invoke failed (attempt %d/%d), retrying in %.1fs%s: %s",
                attempt,
                attempts,
                delay,
                " (provider Retry-After)" if retry_after is not None else "",
                exc,
            )
            time.sleep(delay)
