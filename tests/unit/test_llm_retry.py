"""Unit tests for the LLM retry/backoff wrapper.

These exercise the real ``invoke_with_retry`` implementation; ``time.sleep`` is
patched only so the suite does not actually wait.
"""

import random
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from pipeline.utilities import llm_retry
from pipeline.utilities.llm_retry import (
    DEFAULT_MAX_RETRIES,
    _delay_for_attempt,
    _retry_after_seconds,
    invoke_with_retry,
)

pytestmark = pytest.mark.unit


class _Response:
    def __init__(self, headers: Dict[str, str]):
        self.headers = headers


class _RateLimitError(Exception):
    """Stands in for openai.RateLimitError, which carries .response.headers."""

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        super().__init__("Error code: 429 - token rate limit exceeded")
        if headers is not None:
            self.response = _Response(headers)


class _FakeLLM:
    """Fails ``fail_times`` times, then returns ``result``."""

    def __init__(self, fail_times: int, result: Any = "ok", exc: Any = None):
        self.fail_times = fail_times
        self.result = result
        self.calls = 0
        self._exc = exc or (lambda: _RateLimitError())

    def invoke(self, messages: List[Any]) -> Any:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self._exc()
        return self.result


@pytest.fixture(autouse=True)
def _clear_retry_env(monkeypatch):
    for name in (
        "LLM_MAX_RETRIES",
        "LLM_RETRY_BASE_DELAY_SECONDS",
        "LLM_RETRY_MAX_DELAY_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


class TestInvokeWithRetry:
    def test_first_attempt_succeeds_then_no_sleep(self):
        llm = _FakeLLM(fail_times=0)
        with patch.object(llm_retry.time, "sleep") as sleep:
            assert invoke_with_retry(llm, ["m"]) == "ok"
        assert llm.calls == 1
        sleep.assert_not_called()

    def test_transient_failures_then_succeeds(self):
        llm = _FakeLLM(fail_times=3)
        with patch.object(llm_retry.time, "sleep") as sleep:
            assert invoke_with_retry(llm, ["m"]) == "ok"
        assert llm.calls == 4
        assert sleep.call_count == 3

    def test_budget_exhausted_then_raises_provider_error(self):
        llm = _FakeLLM(fail_times=99)
        with patch.object(llm_retry.time, "sleep"):
            with pytest.raises(_RateLimitError):
                invoke_with_retry(llm, ["m"], max_retries=4)
        assert llm.calls == 4, "attempts are total tries, not retries-after-first"

    def test_default_budget_is_more_patient_than_three_attempts(self):
        """The old implementation gave up after 3 attempts / ~3s."""
        llm = _FakeLLM(fail_times=99)
        with patch.object(llm_retry.time, "sleep"):
            with pytest.raises(_RateLimitError):
                invoke_with_retry(llm, ["m"])
        assert llm.calls == DEFAULT_MAX_RETRIES
        assert DEFAULT_MAX_RETRIES > 3

    def test_explicit_max_retries_overrides_env(self, monkeypatch):
        monkeypatch.setenv("LLM_MAX_RETRIES", "9")
        llm = _FakeLLM(fail_times=99)
        with patch.object(llm_retry.time, "sleep"):
            with pytest.raises(_RateLimitError):
                invoke_with_retry(llm, ["m"], max_retries=2)
        assert llm.calls == 2

    def test_env_raises_attempt_budget(self, monkeypatch):
        monkeypatch.setenv("LLM_MAX_RETRIES", "8")
        llm = _FakeLLM(fail_times=99)
        with patch.object(llm_retry.time, "sleep"):
            with pytest.raises(_RateLimitError):
                invoke_with_retry(llm, ["m"])
        assert llm.calls == 8

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("LLM_MAX_RETRIES", "not-a-number")
        llm = _FakeLLM(fail_times=99)
        with patch.object(llm_retry.time, "sleep"):
            with pytest.raises(_RateLimitError):
                invoke_with_retry(llm, ["m"])
        assert llm.calls == DEFAULT_MAX_RETRIES

    def test_unset_env_uses_defaults(self):
        """Nothing configured must still work — defaults are mandatory."""
        llm = _FakeLLM(fail_times=1)
        with patch.object(llm_retry.time, "sleep"):
            assert invoke_with_retry(llm, ["m"]) == "ok"

    def test_waits_for_provider_retry_after(self, monkeypatch):
        monkeypatch.setenv("LLM_RETRY_MAX_DELAY_SECONDS", "120")
        llm = _FakeLLM(fail_times=1, exc=lambda: _RateLimitError({"retry-after": "47"}))
        with patch.object(llm_retry.time, "sleep") as sleep:
            invoke_with_retry(llm, ["m"])
        assert sleep.call_args_list[0][0][0] == pytest.approx(47.0)

    def test_retry_after_is_capped_by_max_delay(self, monkeypatch):
        monkeypatch.setenv("LLM_RETRY_MAX_DELAY_SECONDS", "10")
        llm = _FakeLLM(
            fail_times=1, exc=lambda: _RateLimitError({"retry-after": "600"})
        )
        with patch.object(llm_retry.time, "sleep") as sleep:
            invoke_with_retry(llm, ["m"])
        assert sleep.call_args_list[0][0][0] == pytest.approx(10.0)


class TestRetryAfterParsing:
    def test_seconds_header(self):
        assert _retry_after_seconds(_RateLimitError({"retry-after": "12"})) == 12.0

    def test_milliseconds_header_preferred(self):
        exc = _RateLimitError({"retry-after-ms": "2500", "retry-after": "9"})
        assert _retry_after_seconds(exc) == pytest.approx(2.5)

    def test_missing_response_returns_none(self):
        assert _retry_after_seconds(_RateLimitError()) is None

    def test_http_date_is_not_parsed(self):
        exc = _RateLimitError({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
        assert _retry_after_seconds(exc) is None

    def test_empty_header_returns_none(self):
        assert _retry_after_seconds(_RateLimitError({"retry-after": ""})) is None

    def test_negative_header_clamped_to_zero(self):
        assert _retry_after_seconds(_RateLimitError({"retry-after": "-5"})) == 0.0


class TestBackoff:
    def test_delay_grows_exponentially_within_jitter_bounds(self):
        random.seed(1234)
        for attempt in (1, 2, 3, 4):
            window = min(30.0, 1.0 * (2 ** (attempt - 1)))
            delay = _delay_for_attempt(attempt, base=1.0, cap=30.0, retry_after=None)
            assert window / 2.0 <= delay <= window

    def test_delay_never_exceeds_cap(self):
        random.seed(7)
        for attempt in range(1, 15):
            delay = _delay_for_attempt(attempt, base=1.0, cap=20.0, retry_after=None)
            assert delay <= 20.0

    def test_jitter_desynchronises_workers(self):
        random.seed(99)
        delays = {
            _delay_for_attempt(5, base=1.0, cap=60.0, retry_after=None)
            for _ in range(20)
        }
        assert len(delays) > 1, "identical delays would re-collide every retry"

    def test_retry_after_takes_precedence_over_backoff(self):
        assert _delay_for_attempt(1, base=1.0, cap=60.0, retry_after=3.0) == 3.0
