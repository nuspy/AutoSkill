"""Bridge to `llmswitch`: the LLM providers of the machine this server runs on.

This is the only place a provider comes from. The registry is the machine's configuration, set by
the administrator, and its file lives outside the repository (``%LOCALAPPDATA%/autoskill`` or
``~/.config/autoskill``) — which is where an API key belongs, because configuration files end up in
commits. It is also what knows about local engines and their VRAM (a model already in memory is
used as it is, instead of loading a second one beside it and losing both), about subscriptions
reused from an already authenticated official CLI, and about the CLI agents themselves.

Every call into the library is blocking — HTTP with `requests`, subprocesses, and on a local
engine possibly a model load — so it runs in a worker thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache, partial
from typing import Any

import anyio.to_thread

from autoskill.config import get_settings
from autoskill.core.errors import AppError
from autoskill.llm.adapters.anthropic import AnthropicProvider
from autoskill.llm.adapters.cli_agent import CliAgentProvider
from autoskill.llm.adapters.openai_compat import OpenAICompatProvider
from autoskill.llm.provider import Capabilities, LlmProvider

log = logging.getLogger(__name__)

#: the five points where AutoSkill calls a model
PURPOSES: tuple[str, ...] = ("interviewer", "supervisor", "author", "coach", "analyst")
#: a purpose with no provider of its own falls back to this consumer
DEFAULT_CONSUMER = "default"
#: llmswitch calls them "consumers": the places in an application that need a model
CONSUMERS: tuple[str, ...] = (*PURPOSES, DEFAULT_CONSUMER)

try:  # optional dependency: without it no purpose can be served, and the panel says so
    import llmswitch as _lib

    IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - depends on the deployment
    _lib = None  # type: ignore[assignment]
    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


class LlmSwitchUnavailable(AppError):
    status_code = 409
    code = "llmswitch_unavailable"


class LlmSwitchUnusable(AppError):
    """Assigned provider that cannot serve a request as configured."""

    status_code = 409
    code = "llmswitch_provider_unusable"


def available() -> bool:
    """True when the library is importable and the administrator has not turned it off."""
    return _lib is not None and get_settings().llmswitch_enabled


@lru_cache
def registry() -> Any:
    """The machine's provider registry (`llmswitch.Registry`)."""
    if _lib is None:
        raise LlmSwitchUnavailable(message=f"the llmswitch library is not installed ({IMPORT_ERROR})")
    settings = get_settings()
    if not settings.llmswitch_enabled:
        raise LlmSwitchUnavailable(message="llmswitch is disabled (AUTOSKILL_LLMSWITCH_ENABLED=0)")
    return _lib.Registry(path=settings.llmswitch_registry, app_name="autoskill", consumers=CONSUMERS)


def reset_registry() -> None:
    """Forget the cached registry — the settings or the file path changed (used by tests)."""
    registry.cache_clear()


async def _off_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))


# --- what the administration screen shows -------------------------------------------------


async def state() -> dict[str, Any]:
    """Everything the settings screen needs, secrets excluded: of a key it only says if it exists."""
    if _lib is None:
        return {"available": False, "reason": IMPORT_ERROR or "llmswitch is not installed", **_empty_state()}
    if not get_settings().llmswitch_enabled:
        return {"available": False, "reason": "disabled by configuration", **_empty_state()}
    reg = registry()
    public = await _off_thread(reg.public)
    subscriptions = await _off_thread(_lib.panoramica)
    agents = await _off_thread(_lib.installati)
    return {
        "available": True,
        "reason": "",
        "version": _lib.__version__,
        "registry_path": str(reg.path),
        "loads_models": get_settings().llmswitch_load_models,
        "providers": public["providers"],
        "types": public["types"],
        "assignments": public["assignments"],
        "consumers": list(CONSUMERS),
        "subscriptions": subscriptions,
        "agents": agents,
    }


def _empty_state() -> dict[str, Any]:
    return {
        "version": "",
        "registry_path": "",
        "loads_models": False,
        "providers": [],
        "types": [],
        "assignments": {},
        "consumers": list(CONSUMERS),
        "subscriptions": [],
        "agents": [],
    }


async def add_provider(fields: dict[str, Any]) -> str:
    return str((await _off_thread(registry().add, fields))["id"])


async def update_provider(pid: str, fields: dict[str, Any]) -> None:
    await _off_thread(registry().update, pid, fields)


async def remove_provider(pid: str) -> None:
    await _off_thread(registry().remove, pid)


async def assign(consumer: str, pid: str | None) -> None:
    await _off_thread(registry().assign, consumer, pid)


async def models(pid: str, force: bool = False) -> list[dict[str, Any]]:
    """Models the provider offers, asked for live (llmswitch caches the remote ones)."""
    return await _off_thread(registry().models, pid, force)


async def probe_models(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Ask a provider for its model list before it is saved, from the fields typed into the form.

    The person adding a provider is asked for a model id they usually do not know: it is a string the
    provider decides, not something anybody memorises. So the form has to be able to fetch the list
    the moment the address and key are entered, before there is a saved provider to point `models()`
    at.

    Done by adding the provider under a scratch id, asking, and removing it again — always, in a
    finally — so the whole per-type endpoint and header logic is the library's, never a second copy of
    it here that would drift. The scratch entry touches the registry file only for the length of the
    call; it is the same file that holds the real provider a moment later.
    """

    def _probe() -> list[dict[str, Any]]:
        reg = registry()
        scratch = reg.add({**{k: v for k, v in fields.items() if v}, "name": "__probe__"})
        pid = scratch["id"]
        try:
            return reg.models(pid, True)
        finally:
            reg.remove(pid)

    return await _off_thread(_probe)


async def test(pid: str) -> dict[str, Any]:
    return await _off_thread(registry().test, pid)


# --- serving a request --------------------------------------------------------------------


@dataclass
class Target:
    """A provider resolved for one purpose, ready to be turned into an adapter."""

    consumer: str
    provider_id: str
    type: str
    api: str
    model: str
    base_url: str = ""
    api_key: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def usage_id(self) -> str:
        # `project_usage_daily.provider_id` is 36 characters wide, and these ids are ours.
        return f"llmswitch:{self.provider_id}"[:36]


def _capabilities(api: str) -> Capabilities:
    if api == "anthropic":
        return Capabilities(tools=True, json_schema=False, vision=True, max_context=200_000)
    if api == "gemini":
        return Capabilities(tools=True, json_schema=True, vision=True, max_context=1_000_000)
    if api == "cli":
        return Capabilities(tools=False, json_schema=False, streaming=False, max_context=200_000)
    return Capabilities(tools=True, json_schema=True, max_context=128_000)


def _resolve(purpose: str) -> Target | None:
    """The provider assigned to `purpose`, or to `default`; None when neither is set."""
    reg = registry()
    load = get_settings().llmswitch_load_models
    for consumer in (purpose, DEFAULT_CONSUMER):
        if consumer not in CONSUMERS:
            continue
        prov = reg.provider_for(consumer)
        if prov is None:
            continue
        spec = _lib.TYPES.get(prov.get("type") or "", {})
        api = str(spec.get("api") or "openai")
        name = str(prov.get("name") or prov.get("id") or "?")
        if api == "cli":
            # No endpoint to call: the model is whatever the CLI was told to use.
            return Target(consumer, prov["id"], prov["type"], api, (prov.get("model") or "").strip())
        resolved = reg.endpoint_for(consumer, carica=load)
        if resolved is None:  # pragma: no cover - provider_for already said there is one
            continue
        base_url, api_key, model = resolved
        headers: dict[str, str] = {}
        if spec.get("auth") == "oauth":
            # A subscription can want more than a token — the Codex backend also asks for the
            # account id — and `endpoint_for` only returns the key.
            headers = {k: v for k, v in reg.headers_for(consumer).items() if k.lower() != "authorization"}
        if not model:
            raise LlmSwitchUnusable(
                message=f"llmswitch provider '{name}' has no model to serve "
                f"'{consumer}' (nothing loaded and nothing configured)"
            )
        return Target(consumer, prov["id"], prov["type"], api, model, base_url, api_key, headers)
    return None


def build_adapter(target: Target) -> LlmProvider:
    caps = _capabilities(target.api)
    if target.api == "cli":
        return CliAgentProvider(agent=target.type, model=target.model, capabilities=caps)
    if target.api == "anthropic":
        # llmswitch points at the model list (`.../v1/models`); the adapter appends `/v1/messages`.
        base = target.base_url[:-3] if target.base_url.endswith("/v1") else target.base_url
        return AnthropicProvider(
            model=target.model,
            api_key=target.api_key,
            base_url=base or "https://api.anthropic.com",
            capabilities=caps,
            timeout=get_settings().llm_request_timeout_seconds,
        )
    if target.api not in ("openai", "lmstudio", "vllm", "gemini"):
        # Google Cloud Code speaks its own protocol and refuses individual plans anyway.
        raise LlmSwitchUnusable(
            message=f"llmswitch provider type '{target.type}' does not expose an "
            "OpenAI-compatible endpoint: AutoSkill cannot use it for inference"
        )
    return OpenAICompatProvider(
        model=target.model,
        base_url=target.base_url,
        api_key=target.api_key or None,
        capabilities=caps,
        extra_headers=target.extra_headers or None,
        timeout=get_settings().llm_request_timeout_seconds,
    )


async def provider_for(purpose: str) -> tuple[LlmProvider, str] | None:
    """`(adapter, id for the usage counters)` for the purpose, or None when nothing is assigned.

    Raises instead of returning None when the administrator *did* assign a provider that cannot
    serve the request: falling through to another one would quietly run the work on a model
    nobody chose, at a price nobody agreed to.
    """
    if not available():
        return None
    target: Target | None = await _off_thread(_resolve, purpose)
    if target is None:
        return None
    log.info(
        "llmswitch: '%s' served by %s (%s) with model '%s'",
        purpose,
        target.provider_id,
        target.type,
        target.model,
    )
    return build_adapter(target), target.usage_id
