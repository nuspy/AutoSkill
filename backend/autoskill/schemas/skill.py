from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel


class SkillOut(ORMModel):
    id: str
    project_id: str
    name: str
    title: str
    summary: str | None
    visibility: str
    development_state: str
    suspend_note: str | None
    current_published_version_id: str | None
    latest_version_id: str | None
    tags: list[str]
    category_id: str | None = None
    install_count: int = 0
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    latest_interview_state: str | None = None
    latest_interview_id: str | None = None


class SkillUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None


class SuspendRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class MemoryEntryOut(ORMModel):
    id: str
    skill_id: str
    kind: str
    title: str
    body: str
    structured: dict
    step_key: str | None
    source: str
    source_ref: str | None
    skill_version_id: str | None
    author_user_id: str | None
    status: str
    superseded_by_id: str | None
    tags: list[str]
    created_at: datetime


class MemoryEntryCreate(BaseModel):
    kind: str
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    structured: dict = Field(default_factory=dict)
    step_key: str | None = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list)


class MemoryEntryUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    structured: dict | None = None
