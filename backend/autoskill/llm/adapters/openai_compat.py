"""OpenAI-compatible chat completions (OpenAI, Ollama, LM Studio, llama.cpp, vLLM, OpenRouter...)."""

from __future__ import annotations

import json
import uuid
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


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        capabilities: Capabilities | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.capabilities = capabilities or Capabilities(tools=True, json_schema=True)
        self._headers = {"Content-Type": "application/json", **(extra_headers or {})}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers, timeout=self._timeout, transport=self._transport
        )

    @staticmethod
    def _to_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
                continue
            item: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in m.tool_calls
                ]
            out.append(item)
        return out

    def _build_body(self, req: ChatRequest, stream: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_messages(req.messages),
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if stream:
            body["stream"] = True
        if req.seed is not None:
            body["seed"] = req.seed
        if req.tools and self.capabilities.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in req.tools
            ]
            if req.tool_choice in ("auto", "none"):
                body["tool_choice"] = req.tool_choice
            elif req.tool_choice:
                body["tool_choice"] = {"type": "function", "function": {"name": req.tool_choice}}
        if req.json_schema and self.capabilities.json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": req.json_schema, "strict": False},
            }
        return body

    async def chat(self, req: ChatRequest) -> ChatResponse:
        async with self._client() as client:
            try:
                res = await client.post("/chat/completions", json=self._build_body(req))
            except httpx.HTTPError as exc:
                raise LlmError(f"connection error: {exc}", retryable=True) from exc
        if res.status_code >= 400:
            raise LlmError(
                f"provider error {res.status_code}: {res.text[:500]}",
                status=res.status_code,
                retryable=res.status_code in (408, 409, 429, 500, 502, 503, 504),
            )
        data = res.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": fn.get("arguments")}
            tool_calls.append(ToolCall(id=tc.get("id") or str(uuid.uuid4()), name=fn.get("name", ""), arguments=args))
        usage = data.get("usage") or {}
        return ChatResponse(
            message=ChatMessage(role="assistant", content=msg.get("content") or "", tool_calls=tool_calls),
            usage=Usage(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)),
            finish_reason=choice.get("finish_reason"),
            raw=data,
            model=data.get("model"),
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        async with self._client() as client:
            async with client.stream("POST", "/chat/completions", json=self._build_body(req, stream=True)) as res:
                if res.status_code >= 400:
                    raise LlmError(f"provider error {res.status_code}", status=res.status_code)
                async for line in res.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                    if delta:
                        yield ChatChunk(delta=delta)

    async def list_models(self) -> list[str]:
        async with self._client() as client:
            res = await client.get("/models")
        if res.status_code >= 400:
            raise LlmError(f"provider error {res.status_code}", status=res.status_code)
        return [m.get("id") for m in (res.json().get("data") or []) if m.get("id")]
