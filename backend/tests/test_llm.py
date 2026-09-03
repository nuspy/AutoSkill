import json

import httpx
import pytest
from pydantic import BaseModel

from autoskill.llm.adapters.anthropic import AnthropicProvider
from autoskill.llm.adapters.openai_compat import OpenAICompatProvider
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.provider import Capabilities, ChatMessage, ChatRequest, LlmError, ToolSpec
from autoskill.llm.structured import extract_json, structured


class Answer(BaseModel):
    color: str
    count: int


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("no json here")


async def test_structured_uses_native_then_repairs():
    fake = FakeLlmProvider([Scripted(text="not json at all"), Scripted(json={"color": "red", "count": 3})])
    result = await structured(fake, ChatRequest(messages=[ChatMessage(role="user", content="q")]), Answer)
    assert result.value.color == "red" and result.repaired is True
    assert result.strategy == "json_schema"
    assert result.usage.input_tokens == 200


async def test_structured_falls_back_to_prompt_strategy():
    fake = FakeLlmProvider([Scripted(text="garbage"), Scripted(text='{"color": "blue", "count": 1}')])
    fake.capabilities = Capabilities(tools=False, json_schema=False)
    result = await structured(
        fake, ChatRequest(messages=[ChatMessage(role="user", content="q")]), Answer, repair_rounds=1
    )
    assert result.strategy == "prompt" and result.value.color == "blue" and result.repaired


async def test_structured_raises_after_all_strategies():
    fake = FakeLlmProvider()
    fake.capabilities = Capabilities(tools=False, json_schema=False)
    with pytest.raises(LlmError):
        await structured(fake, ChatRequest(messages=[ChatMessage(role="user", content="q")]), Answer, repair_rounds=0)


async def test_openai_compat_adapter_request_and_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "respond", "arguments": '{"color": "green", "count": 2}'},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    provider = OpenAICompatProvider(
        model="m", base_url="http://llm.local/v1", api_key="k", transport=httpx.MockTransport(handler)
    )
    req = ChatRequest(
        messages=[ChatMessage(role="system", content="s"), ChatMessage(role="user", content="u")],
        tools=[ToolSpec(name="respond", description="d", parameters={"type": "object"})],
        tool_choice="respond",
        json_schema={"type": "object"},
        seed=3,
    )
    res = await provider.chat(req)
    assert captured["url"] == "http://llm.local/v1/chat/completions"
    assert captured["auth"] == "Bearer k"
    assert captured["body"]["tool_choice"] == {"type": "function", "function": {"name": "respond"}}
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["seed"] == 3
    assert res.message.tool_calls[0].arguments == {"color": "green", "count": 2}
    assert res.usage.input_tokens == 12 and res.finish_reason == "tool_calls"

    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    slow = OpenAICompatProvider(model="m", base_url="http://llm.local/v1", transport=httpx.MockTransport(error_handler))
    with pytest.raises(LlmError) as exc:
        await slow.chat(req)
    assert exc.value.retryable and exc.value.status == 429


async def test_anthropic_adapter_converts_messages_and_tools():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["key"] = request.headers.get("x-api-key")
        return httpx.Response(
            200,
            json={
                "model": "claude",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "hi"},
                    {"type": "tool_use", "id": "t1", "name": "respond", "input": {"color": "red", "count": 1}},
                ],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    provider = AnthropicProvider(model="claude", api_key="secret", transport=httpx.MockTransport(handler))
    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="u"),
            ChatMessage(role="assistant", content="", tool_calls=[]),
            ChatMessage(role="tool", content="result", tool_call_id="t0"),
        ],
        tools=[ToolSpec(name="respond", description="d", parameters={"type": "object"})],
        tool_choice="respond",
    )
    res = await provider.chat(req)
    body = captured["body"]
    assert captured["key"] == "secret"
    assert body["system"] == "sys"
    assert body["tool_choice"] == {"type": "tool", "name": "respond"}
    assert body["tools"][0]["input_schema"] == {"type": "object"}
    assert body["messages"][-1]["content"][0]["type"] == "tool_result"
    assert res.text == "hi" and res.message.tool_calls[0].name == "respond"
    assert res.usage.output_tokens == 2


async def test_demo_provider_answers_every_purpose_with_valid_structures(monkeypatch):
    """AUTOSKILL_LLM_FAKE=demo drives the whole flow without a model (used by the e2e suite)."""
    from autoskill.llm.fake import DemoProvider
    from autoskill.llm.provider import ChatMessage, ChatRequest
    from autoskill.llm.registry import get_fake_provider, set_fake_provider
    from autoskill.llm.structured import structured
    from autoskill.schemas.draft import DraftSpec
    from autoskill.schemas.knowledge import KnowledgeDocModel, QuestionSpec, SupervisorDecision

    set_fake_provider(None)
    monkeypatch.setenv("AUTOSKILL_LLM_FAKE", "demo")
    try:
        demo = get_fake_provider()
        assert isinstance(demo, DemoProvider)

        async def ask(purpose, text, model):
            return (
                await structured(
                    demo, ChatRequest(messages=[ChatMessage(role="user", content=text)], purpose=purpose), model
                )
            ).value

        doc = await ask("interviewer", "Build the knowledge document from this description", KnowledgeDocModel)
        assert [s.key for s in doc.steps] == ["open-sheet", "flag", "send"] and not doc.open_questions
        q = await ask("interviewer", "Ask the person ONE question in English to make progress on gate G3", QuestionSpec)
        assert q.question
        sup = await ask("supervisor", "Decide whether the knowledge document is complete", SupervisorDecision)
        assert sup.decision == "proceed"
        spec = await ask("author", "Write the skill draft", DraftSpec)
        assert len(spec.steps) == 3 and spec.steps[2].side_effects == "irreversible"
        # plain-text summary and scripted overrides still work
        res = await demo.chat(
            ChatRequest(
                messages=[
                    ChatMessage(role="user", content="Write a short summary of the knowledge document for the person")
                ],
                purpose="interviewer",
            )
        )
        assert "Monday" in res.message.content
    finally:
        set_fake_provider(None)
