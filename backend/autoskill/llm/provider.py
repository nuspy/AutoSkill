"""Provider-agnostic chat interface.

Every adapter implements `LlmProvider`. Requests are plain dataclasses so the rest of the
application never imports a vendor SDK. Structured output goes through `structured.py`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # for role == "tool"
    name: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    tools: list[ToolSpec] = field(default_factory=list)
    tool_choice: str | None = None  # "auto" | "none" | "<tool name>"
    temperature: float = 0.2
    max_tokens: int = 2048
    json_schema: dict[str, Any] | None = None  # native structured output when supported
    seed: int | None = None
    purpose: str | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass
class ChatResponse:
    message: ChatMessage
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None
    model: str | None = None

    @property
    def text(self) -> str:
        return self.message.content or ""


@dataclass
class ChatChunk:
    delta: str


@dataclass
class Capabilities:
    tools: bool = True
    json_schema: bool = False
    streaming: bool = True
    vision: bool = False
    max_context: int = 32_000


class LlmProvider(Protocol):
    name: str
    model: str
    capabilities: Capabilities

    async def chat(self, req: ChatRequest) -> ChatResponse: ...

    def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...


class LlmError(Exception):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
