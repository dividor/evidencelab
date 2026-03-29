"""Unit tests for A2A protocol schemas."""

from __future__ import annotations

import pytest

from a2a_server.schemas import (
    Artifact,
    DataPart,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    TaskSendParams,
    TaskState,
    TaskStatus,
    TextPart,
)


class TestTextPart:
    def test_basic(self):
        p = TextPart(text="hello")
        assert p.type == "text"
        assert p.text == "hello"


class TestDataPart:
    def test_basic(self):
        p = DataPart(data={"key": "val"})
        assert p.type == "data"
        assert p.data["key"] == "val"


class TestMessage:
    def test_user_message(self):
        msg = Message(role="user", parts=[TextPart(text="What is climate?")])
        assert msg.role == "user"
        assert len(msg.parts) == 1

    def test_agent_message(self):
        msg = Message(role="agent", parts=[TextPart(text="The answer is...")])
        assert msg.role == "agent"


class TestTaskStatus:
    def test_completed(self):
        s = TaskStatus(state=TaskState.COMPLETED)
        assert s.state == TaskState.COMPLETED

    def test_failed_with_message(self):
        msg = Message(role="agent", parts=[TextPart(text="Error")])
        s = TaskStatus(state=TaskState.FAILED, message=msg)
        assert s.state == TaskState.FAILED
        assert s.message is not None


class TestArtifact:
    def test_text_artifact(self):
        a = Artifact(parts=[TextPart(text="Some answer")])
        assert len(a.parts) == 1
        assert a.artifactId is not None

    def test_artifact_with_name(self):
        a = Artifact(parts=[TextPart(text="token")], name="chunk")
        assert a.name == "chunk"
        assert a.artifactId is not None


class TestJSONRPCRequest:
    def test_parse_tasks_send(self):
        raw = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "tasks/send",
            "params": {
                "id": "task-1",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "hello"}],
                },
            },
        }
        rpc = JSONRPCRequest.model_validate(raw)
        assert rpc.method == "tasks/send"
        assert rpc.id == "req-1"

    def test_missing_method_raises(self):
        with pytest.raises(Exception):
            JSONRPCRequest.model_validate({"jsonrpc": "2.0", "id": 1})


class TestTaskSendParams:
    def test_parses_message(self):
        params = {
            "id": "task-abc",
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "What are findings on WASH?"}],
            },
        }
        p = TaskSendParams.model_validate(params)
        assert p.id == "task-abc"
        assert p.message.role == "user"
        assert isinstance(p.message.parts[0], TextPart)
        assert p.message.parts[0].text == "What are findings on WASH?"

    def test_optional_session_id(self):
        params = {
            "id": "t1",
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "query"}],
            },
        }
        p = TaskSendParams.model_validate(params)
        assert p.sessionId is None


class TestJSONRPCResponse:
    def test_success_response(self):
        r = JSONRPCResponse(id="req-1", result={"status": "ok"})
        assert r.error is None
        assert r.result["status"] == "ok"

    def test_serialise_excludes_none(self):
        r = JSONRPCResponse(id=1, result={"x": 1})
        dumped = r.model_dump(exclude_none=True)
        assert "error" not in dumped
