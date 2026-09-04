from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LlmSwitchState(BaseModel):
    """The machine's provider registry as the settings screen sees it: never a secret."""

    available: bool
    reason: str = ""
    version: str = ""
    registry_path: str = ""
    loads_models: bool = False
    providers: list[dict[str, Any]] = Field(default_factory=list)
    types: list[dict[str, Any]] = Field(default_factory=list)
    assignments: dict[str, str] = Field(default_factory=dict)
    consumers: list[str] = Field(default_factory=list)
    subscriptions: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)


class LlmSwitchProviderCreate(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    embed_model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=2000)


class LlmSwitchProviderUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    embed_model: str | None = Field(default=None, max_length=200)
    # Sent only when the administrator typed one: an absent field leaves the stored key alone,
    # an empty string clears it.
    api_key: str | None = Field(default=None, max_length=2000)


class LlmSwitchAssign(BaseModel):
    purpose: str = Field(min_length=1, max_length=64)
    provider: str | None = None


class LlmSwitchModels(BaseModel):
    models: list[dict[str, Any]] = Field(default_factory=list)
    # A provider that is down or holds a stale key is a normal state of a settings screen,
    # not a failure of the request that asked: the reason travels with the empty list.
    error: str = ""


class LlmSwitchTestResult(BaseModel):
    ok: bool
    models: int = 0
    sample: list[str] = Field(default_factory=list)
    error: str = ""
