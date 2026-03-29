"""Integration tests for the A2A server.

These tests run inside Docker against the A2A server with real data
ingested by the pipeline. They verify end-to-end task execution via
HTTP POST to the /a2a endpoint.
"""

import json
import os

import requests

_BASE_URL = os.getenv("MCP_BASE_URL", "http://mcp:8001")
A2A_URL = _BASE_URL + "/a2a"
AGENT_CARD_URL = _BASE_URL + "/.well-known/agent.json"
API_KEY = os.getenv("API_SECRET_KEY", os.getenv("REACT_APP_API_KEY", ""))


def _a2a_call(method: str, params: dict | None = None, call_id: int = 1) -> dict:
    """Send a JSON-RPC call to the A2A server and return the parsed response."""
    body = {"jsonrpc": "2.0", "method": method, "id": call_id, "params": params or {}}
    resp = requests.post(
        A2A_URL,
        json=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-Key": API_KEY,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


class TestA2AIntegration:
    """A2A server integration tests using pipeline-ingested data."""

    def test_agent_card(self):
        """Agent Card is publicly accessible and well-formed."""
        resp = requests.get(AGENT_CARD_URL, timeout=10)
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"]
        assert "/a2a" in card["url"]
        assert "skills" in card
        skill_ids = {s["id"] for s in card["skills"]}
        assert "research" in skill_ids
        assert "search" in skill_ids

    def test_agent_card_no_auth_required(self):
        """Agent Card endpoint is public — no API key needed."""
        resp = requests.get(AGENT_CARD_URL, timeout=10)
        assert resp.status_code == 200

    def test_search_task_completes(self):
        """tasks/send with search skill returns a completed task with artifacts."""
        data = _a2a_call(
            "tasks/send",
            {
                "message": {
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": "search for health evaluations"}
                    ],
                    "metadata": {"skill": "search", "limit": 3},
                }
            },
        )
        assert "error" not in data
        task = data["result"]
        assert task["status"]["state"] == "completed"
        assert len(task["artifacts"]) > 0
        artifact = task["artifacts"][0]
        assert artifact["name"] == "search_results"
        text_parts = [p for p in artifact["parts"] if p.get("type") == "text"]
        assert text_parts

    def test_search_task_has_structured_data(self):
        """Search task artifact contains a structured data part with result metadata."""
        data = _a2a_call(
            "tasks/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "search for education"}],
                    "metadata": {"skill": "search", "limit": 2},
                }
            },
        )
        task = data["result"]
        assert task["status"]["state"] == "completed"
        artifact = task["artifacts"][0]
        data_parts = [p for p in artifact["parts"] if p.get("type") == "data"]
        assert data_parts, "Expected at least one data part in search results"
        search_data = data_parts[0]["data"]
        assert "total" in search_data
        assert "results" in search_data
        assert "query" in search_data

    def test_search_task_returns_history(self):
        """Completed task includes the original message in history."""
        data = _a2a_call(
            "tasks/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "search for water"}],
                    "metadata": {"skill": "search", "limit": 1},
                }
            },
        )
        task = data["result"]
        assert task["status"]["state"] == "completed"
        assert len(task["history"]) > 0
        assert task["history"][0]["role"] == "user"

    def test_tasks_get_retrieves_submitted_task(self):
        """tasks/get returns a previously submitted task by ID."""
        task_id = "integration-test-get-001"
        submit = _a2a_call(
            "tasks/send",
            {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "search for water"}],
                    "metadata": {"skill": "search", "limit": 1},
                },
            },
        )
        assert submit["result"]["status"]["state"] == "completed"

        get_resp = _a2a_call("tasks/get", {"id": task_id})
        assert "error" not in get_resp
        assert get_resp["result"]["id"] == task_id
        assert get_resp["result"]["status"]["state"] == "completed"

    def test_tasks_get_unknown_returns_error(self):
        """tasks/get with unknown task ID returns A2A_TASK_NOT_FOUND error."""
        data = _a2a_call("tasks/get", {"id": "nonexistent-task-xyz-abc"})
        assert "error" in data
        assert data["error"]["code"] == -32001  # A2A_TASK_NOT_FOUND

    def test_tasks_cancel_completed_task_fails(self):
        """Cancelling a completed task returns A2A_UNSUPPORTED_OPERATION."""
        task_id = "integration-test-cancel-001"
        _a2a_call(
            "tasks/send",
            {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "search for health"}],
                    "metadata": {"skill": "search", "limit": 1},
                },
            },
        )
        cancel = _a2a_call("tasks/cancel", {"id": task_id})
        assert "error" in cancel
        assert cancel["error"]["code"] == -32004  # A2A_UNSUPPORTED_OPERATION

    def test_invalid_method_returns_error(self):
        """Unknown method name returns JSONRPC_METHOD_NOT_FOUND error."""
        data = _a2a_call("tasks/unknown")
        assert "error" in data
        assert data["error"]["code"] == -32601  # JSONRPC_METHOD_NOT_FOUND

    def test_invalid_json_returns_parse_error(self):
        """Non-JSON body returns JSONRPC_PARSE_ERROR."""
        resp = requests.post(
            A2A_URL,
            data=b"this-is-not-json",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-API-Key": API_KEY,
            },
            timeout=10,
        )
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32700  # JSONRPC_PARSE_ERROR

    def test_auth_rejects_invalid_key(self):
        """A2A endpoint rejects requests with an invalid API key."""
        resp = requests.post(
            A2A_URL,
            json={
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "id": 1,
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "test"}],
                    }
                },
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-API-Key": "invalid-key-xyz-000",
            },
            timeout=10,
        )
        assert resp.status_code in (401, 403)

    def test_streaming_task_returns_sse_events(self):
        """tasks/sendSubscribe streams SSE events for a search task."""
        resp = requests.post(
            A2A_URL,
            json={
                "jsonrpc": "2.0",
                "method": "tasks/sendSubscribe",
                "id": 1,
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "search for climate"}],
                        "metadata": {"skill": "search", "limit": 1},
                    }
                },
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-API-Key": API_KEY,
            },
            stream=True,
            timeout=60,
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = []
        for line in resp.iter_lines(decode_unicode=True):
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))

        assert len(events) > 0, "Expected at least one SSE event"
        # Events are JSON-RPC envelopes per the A2A spec:
        # {"jsonrpc": "2.0", "id": ..., "result": {<event payload>}}
        # Unwrap the envelope before checking payload fields.
        first_payload = events[0].get("result", events[0])
        assert first_payload.get("status", {}).get("state") == "working"
        # Last event must be completed status with final=True
        last_payload = events[-1].get("result", events[-1])
        assert last_payload.get("status", {}).get("state") == "completed"
        assert last_payload.get("final") is True

    def test_sendsubscribe_requires_event_stream_accept(self):
        """tasks/sendSubscribe returns error if Accept header does not include text/event-stream."""
        data = _a2a_call(
            "tasks/sendSubscribe",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "search for health"}],
                    "metadata": {"skill": "search"},
                }
            },
        )
        # The default _a2a_call uses Accept: application/json, not text/event-stream
        assert "error" in data
        assert data["error"]["code"] == -32004  # A2A_UNSUPPORTED_OPERATION

    def test_research_task_returns_summary_and_citations(self):
        """tasks/send with research skill returns a synthesised summary with citations."""
        data = _a2a_call(
            "tasks/send",
            {
                "message": {
                    "role": "user",
                    "parts": [
                        {
                            "type": "text",
                            "text": "what are the key findings on humanitarian evaluations?",
                        }
                    ],
                    "metadata": {"skill": "research"},
                }
            },
            call_id=99,
        )

        assert "error" not in data, f"Unexpected error: {data.get('error')}"
        task = data["result"]

        # Task must complete successfully
        assert task["status"]["state"] == "completed"
        assert len(task["artifacts"]) > 0

        artifact = task["artifacts"][0]
        assert artifact["name"] == "research_response"

        # Must contain a text part with a substantive summary
        text_parts = [p for p in artifact["parts"] if p.get("type") == "text"]
        assert text_parts, "Research artifact must include a text summary"
        summary = text_parts[0]["text"]
        assert len(summary) > 50, "Summary text should be substantive, not empty"

        # Must contain a data part (always present; citations list may be empty if no data)
        data_parts = [p for p in artifact["parts"] if p.get("type") == "data"]
        assert data_parts, "Research artifact must include a structured data part"
        research_data = data_parts[0]["data"]

        assert "citations" in research_data, "Data part must include 'citations'"
        assert "references" in research_data, "Data part must include 'references'"
        citations = research_data["citations"]
        assert isinstance(citations, list)

        # Citation data-quality assertions require indexed documents in Qdrant
        if not citations:
            import pytest as _pytest

            _pytest.skip(
                "No indexed documents available — skipping citation assertions"
            )

        # Each citation should carry basic document metadata
        first_cit = citations[0]
        has_title = "title" in first_cit
        has_source = "source" in first_cit or "doc_id" in first_cit
        assert (
            has_title or has_source
        ), f"Citation needs a title or source identifier; got: {first_cit}"

    def test_invalid_data_source_returns_error(self):
        """tasks/send with an unknown data_source returns a task-failed status."""
        data = _a2a_call(
            "tasks/send",
            {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "search for climate"}],
                    "metadata": {
                        "skill": "search",
                        "data_source": "../../etc/passwd",
                    },
                }
            },
        )
        # Should either return a JSON-RPC error or a failed task — not silently succeed
        task = data.get("result", {})
        has_rpc_error = "error" in data
        has_failed_task = task.get("status", {}).get("state") == "failed"
        assert (
            has_rpc_error or has_failed_task
        ), "An invalid data_source must not result in a completed task"
