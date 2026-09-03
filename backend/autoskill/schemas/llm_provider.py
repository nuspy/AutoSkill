from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    adapter: str
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=2000)
    purposes: list[str] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)
    is_default: bool = False
    is_enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=2000)
    purposes: list[str] | None = None
    extra: dict | None = None
    is_default: bool | None = None
    is_enabled: bool | None = None


class ProviderOut(ORMModel):
    id: str
    scope: str
    project_id: str | None
    name: str
    adapter: str
    base_url: str | None
    model: str
    models: list[str]
    purposes: list[str]
    extra: dict
    is_default: bool
    is_enabled: bool
    has_api_key: bool = False
    health: dict
    created_at: datetime


class ProviderTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
    models: list[str] = Field(default_factory=list)
    capabilities: dict = Field(default_factory=dict)
