"""Anthropic Messages API adapter (httpx, no SDK dependency)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from autoskill.llm.provider import (
    Capabilities,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LlmError,
    ToolCall,
    Usage,
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        capabilities: Capabilities | None = None,
        timeout: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.capabilities = capabilities or Capabilities(
            tools=True, json_schema=False, vision=True, max_context=200_000
        )
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers, timeout=self._timeout, transport=self._transport
        )

    @staticmethod
    def _convert(messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            elif m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif m.role == "assistant" and m.tool_calls:
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                out.append({"role": "assistant", "content": content})
            else:
                out.append({"role": m.role, "content": m.content})
        return "\n\n".join(system_parts), out

    def _build_body(self, req: ChatRequest, stream: bool = False) -> dict[str, Any]:
        system, messages = self._convert(req.messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
        }
        if system:
            body["system"] = system
        if stream:
            body["stream"] = True
        if req.tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in req.tools
            ]
            if req.tool_choice == "auto":
                body["tool_choice"] = {"type": "auto"}
            elif req.tool_choice and req.tool_choice != "none":
                body["tool_choice"] = {"type": "tool", "name": req.tool_choice}
        return body

    async def chat(self, req: ChatRequest) -> ChatResponse:
        async with self._client() as client:
            try:
                res = await client.post("/v1/messages", json=self._build_body(req))
            except httpx.HTTPError as exc:
                raise LlmError(f"connection error: {exc}", retryable=True) from exc
        if res.status_code >= 400:
            raise LlmError(
                f"provider error {res.status_code}: {res.text[:500]}",
                status=res.status_code,
                retryable=res.status_code in (408, 409, 429, 500, 502, 503, 504, 529),
            )
        data = res.json()
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {}))
        usage = data.get("usage") or {}
        return ChatResponse(
            message=ChatMessage(role="assistant", content="".join(text_parts), tool_calls=tool_calls),
            usage=Usage(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)),
            finish_reason=data.get("stop_reason"),
            raw=data,
            model=data.get("model"),
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        async with self._client() as client:
            async with client.stream("POST", "/v1/messages", json=self._build_body(req, stream=True)) as res:
                if res.status_code >= 400:
                    raise LlmError(f"provider error {res.status_code}", status=res.status_code)
                async for line in res.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield ChatChunk(delta=delta["text"])
