"""Scripted provider for tests and `AUTOSKILL_LLM_FAKE=1` demos.

Responses are matched by `purpose` (and optionally by a substring of the last user message) in
order; unmatched calls return the default reply. Every call is recorded for assertions.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from autoskill.llm.provider import (
    Capabilities,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    Usage,
)


@dataclass
class Scripted:
    purpose: str | None = None
    contains: str | None = None
    text: str | None = None
    json: Any = None
    tool_calls: list[tuple[str, dict[str, Any]]] | None = None


class FakeLlmProvider:
    name = "fake"

    def __init__(self, scripts: list[Scripted] | None = None, default_json: Any = None) -> None:
        self.model = "fake-model"
        self.capabilities = Capabilities(tools=True, json_schema=True)
        self._scripts: deque[Scripted] = deque(scripts or [])
        self._default_json = default_json
        self.calls: list[ChatRequest] = []

    def script(self, *items: Scripted) -> None:
        self._scripts.extend(items)

    def _match(self, req: ChatRequest) -> Scripted | None:
        last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        for i, s in enumerate(self._scripts):
            if s.purpose and s.purpose != req.purpose:
                continue
            if s.contains and s.contains not in last_user:
                continue
            del self._scripts[i]
            return s
        return None

    async def chat(self, req: ChatRequest) -> ChatResponse:
        self.calls.append(req)
        s = self._match(req)
        usage = Usage(input_tokens=100, output_tokens=50)
        if s is None:
            content = json.dumps(self._default_json) if self._default_json is not None else "ok"
            return ChatResponse(message=ChatMessage(role="assistant", content=content), usage=usage)
        if s.tool_calls:
            calls = [ToolCall(id=f"call_{i}", name=n, arguments=a) for i, (n, a) in enumerate(s.tool_calls)]
            return ChatResponse(
                message=ChatMessage(role="assistant", content=s.text or "", tool_calls=calls), usage=usage
            )
        content = s.text if s.text is not None else json.dumps(s.json)
        return ChatResponse(message=ChatMessage(role="assistant", content=content), usage=usage)

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        res = await self.chat(req)
        for word in res.text.split(" "):
            yield ChatChunk(delta=word + " ")
