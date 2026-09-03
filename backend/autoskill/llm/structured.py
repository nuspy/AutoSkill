"""Structured output ladder: native JSON schema -> forced tool call -> fenced JSON + repair."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from autoskill.llm.provider import ChatMessage, ChatRequest, LlmError, LlmProvider, ToolSpec, Usage

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class StructuredResult:
    value: BaseModel
    usage: Usage
    strategy: str
    repaired: bool = False


def extract_json(text: str) -> Any:
    text = text.strip()
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass
    # last resort: first {...} or [...] block
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON object found in model output")


def _schema_of(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.setdefault("additionalProperties", False)
    return schema


async def structured(
    provider: LlmProvider, req: ChatRequest, model: type[T], *, repair_rounds: int = 1
) -> StructuredResult:
    """Ask the provider for a `model` instance using the best strategy it supports."""
    schema = _schema_of(model)
    caps = provider.capabilities
    total = Usage()

    def add_usage(u: Usage) -> None:
        total.input_tokens += u.input_tokens
        total.output_tokens += u.output_tokens

    strategies: list[str] = []
    if caps.json_schema:
        strategies.append("json_schema")
    if caps.tools:
        strategies.append("tool")
    strategies.append("prompt")

    last_error: Exception | None = None
    for strategy in strategies:
        messages = list(req.messages)
        attempt_req = ChatRequest(
            messages=messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            seed=req.seed,
            purpose=req.purpose,
        )
        if strategy == "json_schema":
            attempt_req.json_schema = schema
        elif strategy == "tool":
            attempt_req.tools = [
                ToolSpec(name="respond", description="Return the structured answer.", parameters=schema)
            ]
            attempt_req.tool_choice = "respond"
        else:
            messages.append(
                ChatMessage(
                    role="system",
                    content="Answer ONLY with a JSON object matching this JSON schema, no prose:\n"
                    + json.dumps(schema),
                )
            )
        for round_ in range(repair_rounds + 1):
            try:
                res = await provider.chat(attempt_req)
            except LlmError:
                raise
            add_usage(res.usage)
            try:
                if strategy == "tool" and res.message.tool_calls:
                    payload = res.message.tool_calls[0].arguments
                else:
                    payload = extract_json(res.text)
                value = model.model_validate(payload)
                return StructuredResult(value=value, usage=total, strategy=strategy, repaired=round_ > 0)
            except (ValueError, ValidationError) as exc:
                last_error = exc
                if round_ < repair_rounds:
                    attempt_req.messages = attempt_req.messages + [
                        res.message,
                        ChatMessage(
                            role="user",
                            content=f"Your previous answer was invalid ({str(exc)[:300]}). "
                            "Reply again with ONLY a valid JSON object matching the schema.",
                        ),
                    ]
                    continue
                break
    raise LlmError(f"structured output failed: {last_error}")
