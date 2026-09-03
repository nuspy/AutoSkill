from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel


class DeviceOut(ORMModel):
    id: str
    name: str
    os: str | None
    agent_targets: list[str]
    cli_version: str | None
    last_seen_at: datetime | None
    created_at: datetime


class DeviceHeartbeat(BaseModel):
    agent_targets: list[str] | None = None
    cli_version: str | None = Field(default=None, max_length=40)
    os: str | None = Field(default=None, max_length=80)
