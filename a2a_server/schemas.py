"""A2A protocol Pydantic models (Google Agent-to-Agent spec)."""

from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Metadata safety helpers (mirrors ui.backend.auth.schemas)
# ---------------------------------------------------------------------------

_MAX_METADATA_DEPTH = 10
_MAX_METADATA_SIZE = 32_000  # 32 KB — generous for task metadata


def _check_depth(obj: Any, depth: int = 0) -> None:
    if depth > _MAX_METADATA_DEPTH:
        raise ValueError(
            f"metadata nesting exceeds maximum depth of {_MAX_METADATA_DEPTH}"
        )
    if isinstance(obj, dict):
        for v in obj.values():
            _check_depth(v, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _check_depth(item, depth + 1)


def _validate_metadata(v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate metadata depth and size to prevent DoS via deeply nested payloads."""
    if v is None:
        return v
    _check_depth(v)
    if len(json.dumps(v, default=str)) > _MAX_METADATA_SIZE:
        raise ValueError(
            f"metadata payload exceeds maximum size of {_MAX_METADATA_SIZE} characters"
        )
    return v


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------


class TextPart(BaseModel):
    # Accept both 'type' (old spec) and 'kind' (new spec)
    type: str = "text"
    kind: str = "text"
    text: str


class DataPart(BaseModel):
    type: str = "data"
    kind: str = "data"
    data: Dict[str, Any]

    @field_validator("data")
    @classmethod
    def validate_data(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        _check_depth(v)
        return v


Part = Union[TextPart, DataPart]


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class Message(BaseModel):
    kind: str = "message"
    role: str  # "user" or "agent"
    parts: List[Part]
    messageId: Optional[str] = None
    taskId: Optional[str] = None
    contextId: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return _validate_metadata(v)


# ---------------------------------------------------------------------------
# Task state
# ---------------------------------------------------------------------------


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TaskStatus(BaseModel):
    state: TaskState
    message: Optional[Message] = None
    timestamp: Optional[str] = None


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class Artifact(BaseModel):
    artifactId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: Optional[str] = None
    description: Optional[str] = None
    parts: List[Part]
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class Task(BaseModel):
    kind: str = "task"
    id: str
    contextId: str
    sessionId: Optional[str] = None
    status: TaskStatus
    artifacts: Optional[List[Artifact]] = None
    history: Optional[List[Message]] = None
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# JSON-RPC envelopes
# ---------------------------------------------------------------------------


class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Union[str, int]
    method: str
    params: Optional[Any] = None


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Union[str, int]
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None


# ---------------------------------------------------------------------------
# Method params
# ---------------------------------------------------------------------------


class TaskSendParams(BaseModel):
    id: Optional[str] = None
    sessionId: Optional[str] = None
    message: Message
    historyLength: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class TaskQueryParams(BaseModel):
    id: str
    historyLength: Optional[int] = None


class TaskIdParams(BaseModel):
    id: str


# ---------------------------------------------------------------------------
# Streaming events (message/stream / tasks/sendSubscribe)
# ---------------------------------------------------------------------------


class TaskStatusUpdateEvent(BaseModel):
    kind: str = "status-update"
    taskId: str
    contextId: str
    status: TaskStatus
    final: bool = False
    metadata: Optional[Dict[str, Any]] = None


class TaskArtifactUpdateEvent(BaseModel):
    kind: str = "artifact-update"
    taskId: str
    contextId: str
    artifact: Artifact
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    inputModes: List[str] = Field(default_factory=lambda: ["text/plain"])
    outputModes: List[str] = Field(default_factory=lambda: ["text/plain"])


class AgentCapabilities(BaseModel):
    streaming: bool = True
    pushNotifications: bool = False
    stateTransitionHistory: bool = False


class AgentAuthentication(BaseModel):
    schemes: List[str]
    credentials: Optional[str] = None


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    protocolVersion: str = "1.0"
    preferredTransport: str = "JSONRPC"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    defaultInputModes: List[str] = Field(default_factory=lambda: ["text/plain"])
    defaultOutputModes: List[str] = Field(default_factory=lambda: ["text/plain"])
    authentication: AgentAuthentication
    skills: List[AgentSkill]
    documentationUrl: Optional[str] = None


# ---------------------------------------------------------------------------
# Error codes (JSON-RPC + A2A extensions)
# ---------------------------------------------------------------------------

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

A2A_TASK_NOT_FOUND = -32001
A2A_TASK_NOT_CANCELABLE = -32002
A2A_PUSH_NOT_SUPPORTED = -32003
A2A_UNSUPPORTED_OPERATION = -32004
