"""Which provider answers for a purpose, and the adapter to talk to it.

There is one source of truth: the llmswitch registry of the machine the server runs on, where the
administrator assigns a provider to each purpose (see `llm/switch.py`). A purpose with none of its
own falls back to the `default` consumer. Nothing about the choice lives in the database — a model
and its API key belong to the machine, not to a row somebody can edit through the application.

Tests, and `AUTOSKILL_LLM_FAKE`, short-circuit all of it with a scripted provider.
"""

from __future__ import annotations

import os

from autoskill.core.errors import AppError
from autoskill.llm import switch
from autoskill.llm.fake import DemoProvider, FakeLlmProvider
from autoskill.llm.provider import LlmProvider

_fake: FakeLlmProvider | None = None


def set_fake_provider(provider: FakeLlmProvider | None) -> None:
    """Tests inject a scripted provider; `AUTOSKILL_LLM_FAKE=1` uses a default one."""
    global _fake
    _fake = provider


def get_fake_provider() -> FakeLlmProvider | None:
    global _fake
    mode = os.environ.get("AUTOSKILL_LLM_FAKE")
    if _fake is None and mode == "1":
        _fake = FakeLlmProvider()
    elif _fake is None and mode == "demo":
        _fake = DemoProvider()
    return _fake


class NoProviderConfigured(AppError):
    status_code = 409
    code = "no_llm_provider"


async def get_provider(purpose: str) -> tuple[LlmProvider, str | None]:
    """The adapter for this purpose, and the id the usage counters record it under."""
    fake = get_fake_provider()
    if fake is not None:
        return fake, None
    chosen = await switch.provider_for(purpose)
    if chosen is None:
        raise NoProviderConfigured(
            message="No LLM provider configured. An administrator sets one up in Administration → AI providers."
        )
    return chosen
