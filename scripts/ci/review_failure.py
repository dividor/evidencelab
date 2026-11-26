"""Report a failed review without printing the model's execution log."""

import json
import os
from pathlib import Path

ERROR_REASONS = {
    "credit balance is too low": "API credits are exhausted",
    "insufficient credits": "API credits are exhausted",
    "spending limit": "API spending limit reached",
    "usage limit": "API usage limit reached",
    "rate limit": "API rate limit reached",
    "authentication failed": "API authentication failed",
    "invalid bearer token": "API authentication failed",
    "model not found": "The review model is unavailable",
    "overloaded": "The review service is overloaded",
}


def summarize_failure(messages: list[dict]) -> str:
    """Extract the HTTP status and a known reason from an errored SDK result."""
    result = next(
        (message for message in reversed(messages) if message.get("type") == "result"),
        {},
    )
    if result.get("is_error") is not True:
        return "The execution log contains no failed SDK result."
    status = result.get("api_error_status")
    details = json.dumps([result.get("result"), result.get("errors")]).lower()
    reason = next(
        (label for phrase, label in ERROR_REASONS.items() if phrase in details),
        "The SDK gave no recognized error reason",
    )
    if isinstance(status, int) and 400 <= status <= 599:
        return f"Review API returned HTTP {status}. {reason}."
    return f"Review execution failed. {reason}."


def report_failure(runner_temp: Path, execution_file: str) -> str:
    """Read only the execution log written inside the runner's temp directory."""
    if execution_file:
        path = Path(execution_file).resolve()
        if path.is_relative_to(runner_temp.resolve()) and path.is_file():
            return summarize_failure(json.loads(path.read_text(encoding="utf-8")))
    return "The review action provided no execution log in the runner's temp directory."


if __name__ == "__main__":
    print(
        report_failure(
            Path(os.environ["RUNNER_TEMP"]), os.environ["REVIEW_EXECUTION_FILE"]
        )
    )
