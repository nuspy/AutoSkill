"""Subscription CLIs (Codex, Claude Code, Antigravity) driven through `llmswitch.agents`.

These are agents, not completion endpoints: they answer in seconds rather than milliseconds,
report no token counts, expose no tool protocol and cannot stream. They earn their place
because running the official client is the only compliant way to spend a subscription the
administrator already pays for.

The command runs in an empty throw-away directory: an agent reads the files around it to build
context, and the server's working directory is none of its business.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import partial

import anyio.to_thread

from autoskill.llm.provider import Capabilities, ChatChunk, ChatMessage, ChatRequest, ChatResponse, LlmError, Usage

_ROLES = {"user": "User", "assistant": "Assistant", "tool": "Tool result"}


class CliAgentProvider:
    """Adapter over one `llmswitch` CLI agent (`codex_cli`, `claude_cli`, `antigravity`)."""

    name = "cli_agent"

    def __init__(
        self,
        agent: str,
        model: str = "",
        capabilities: Capabilities | None = None,
        timeout: float = 600.0,
    ) -> None:
        self.agent = agent
        self.model = model
        self.capabilities = capabilities or Capabilities(tools=False, json_schema=False, streaming=False)
        self._timeout = timeout

    @staticmethod
    def _flatten(messages: list[ChatMessage]) -> str:
        """One prompt out of the conversation: an agent is invoked once, not turn by turn."""
        system = [m.content.strip() for m in messages if m.role == "system" and m.content.strip()]
        turns = [
            f"{_ROLES.get(m.role, m.role)}: {m.content.strip()}"
            for m in messages
            if m.role != "system" and m.content.strip()
        ]
        return "\n\n".join([*system, *turns]).strip()

    async def chat(self, req: ChatRequest) -> ChatResponse:
        from llmswitch import AgentError, genera

        prompt = self._flatten(req.messages)
        if not prompt:
            raise LlmError("nothing to ask the agent: the request carries no text")
        try:
            text = await anyio.to_thread.run_sync(
                partial(genera, self.agent, prompt, model=self.model, timeout_s=self._timeout)
            )
        except AgentError as exc:
            # Missing CLI, expired login or a run that never came back: none of them get better
            # by asking again straight away.
            raise LlmError(f"{self.agent}: {exc}", retryable=False) from exc
        return ChatResponse(
            message=ChatMessage(role="assistant", content=text),
            usage=Usage(),  # the CLIs report no token counts
            finish_reason="stop",
            model=self.model or self.agent,
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        """The CLIs answer in one go; the whole text arrives as a single chunk."""
        res = await self.chat(req)
        yield ChatChunk(delta=res.text)
