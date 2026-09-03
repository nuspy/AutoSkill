"""Resolve the provider to use for a (project, purpose) and build the adapter."""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.crypto import decrypt
from autoskill.core.errors import AppError
from autoskill.llm.adapters.anthropic import AnthropicProvider
from autoskill.llm.adapters.openai_compat import OpenAICompatProvider
from autoskill.llm.fake import DemoProvider, FakeLlmProvider
from autoskill.llm.provider import Capabilities, LlmProvider
from autoskill.models.llm_provider import LlmProvider as LlmProviderRow

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


def build_provider(row: LlmProviderRow) -> LlmProvider:
    api_key = decrypt(row.api_key_encrypted) if row.api_key_encrypted else None
    extra = row.extra or {}
    caps = Capabilities(
        tools=bool(extra.get("supports_tools", True)),
        json_schema=bool(extra.get("supports_json_schema", row.adapter in ("openai", "openai_compat", "openrouter"))),
        vision=bool(extra.get("supports_vision", False)),
        max_context=int(extra.get("max_context", 32_000)),
    )
    if row.adapter == "anthropic":
        if not api_key:
            raise NoProviderConfigured(message="anthropic provider needs an API key")
        return AnthropicProvider(
            model=row.model, api_key=api_key, base_url=row.base_url or "https://api.anthropic.com", capabilities=caps
        )
    base_urls = {
        "openai": "https://api.openai.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "google": "https://generativelanguage.googleapis.com/v1beta/openai",
        "openai_compat": "http://localhost:11434/v1",
    }
    headers = (
        {"HTTP-Referer": "https://autoskill.local", "X-Title": "AutoSkill"} if row.adapter == "openrouter" else None
    )
    return OpenAICompatProvider(
        model=row.model,
        base_url=row.base_url or base_urls.get(row.adapter, base_urls["openai_compat"]),
        api_key=api_key,
        capabilities=caps,
        extra_headers=headers,
    )


async def resolve_provider_row(session: AsyncSession, project_id: str | None, purpose: str) -> LlmProviderRow | None:
    """Purpose-specific project provider -> project default -> purpose-specific system -> system default."""
    candidates: list[LlmProviderRow] = []
    if project_id:
        res = await session.execute(
            select(LlmProviderRow).where(LlmProviderRow.project_id == project_id, LlmProviderRow.is_enabled.is_(True))
        )
        candidates.extend(res.scalars().all())
    res = await session.execute(
        select(LlmProviderRow).where(LlmProviderRow.scope == "system", LlmProviderRow.is_enabled.is_(True))
    )
    system_rows = list(res.scalars().all())
    for pool in (candidates, system_rows):
        for row in pool:
            if purpose in (row.purposes or []):
                return row
        for row in pool:
            if row.is_default:
                return row
        if pool:
            return pool[0]
    return None


async def get_provider(session: AsyncSession, project_id: str | None, purpose: str) -> tuple[LlmProvider, str | None]:
    fake = get_fake_provider()
    if fake is not None:
        return fake, None
    row = await resolve_provider_row(session, project_id, purpose)
    if row is None:
        raise NoProviderConfigured(message="No LLM provider configured. Add one in Settings.")
    return build_provider(row), row.id
