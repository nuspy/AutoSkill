from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class AuditOut(BaseModel):
    id: str
    actor_user_id: str | None
    project_id: str | None
    action: str
    subject_type: str | None
    subject_id: str | None
    before: dict | None
    after: dict | None
    created_at: str


class JobOut(BaseModel):
    id: str
    type: str
    status: str
    progress: int
    message: str | None
    error: str | None
    project_id: str | None
    user_id: str | None
    created_at: str
    finished_at: str | None


class StatsOut(BaseModel):
    users: int
    projects: int
    devices: int
    jobs_running: int
