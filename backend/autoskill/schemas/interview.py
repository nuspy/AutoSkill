from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel


class InterviewStart(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)
    language: str = Field(default="en", max_length=8)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    skill_id: str | None = None


class InterviewAnswer(BaseModel):
    text: str = Field(default="", max_length=20000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class InterviewConfirm(BaseModel):
    confirmed: bool
    text: str | None = Field(default=None, max_length=5000)


class MessageOut(ORMModel):
    id: str
    ordinal: int
    role: str
    content: str
    attachments: list[dict]
    meta: dict
    created_at: datetime


class KnowledgeOut(ORMModel):
    id: str
    revision: int
    doc: dict
    completeness: dict
    frozen: bool
    created_at: datetime


class SessionOut(ORMModel):
    id: str
    project_id: str
    skill_id: str
    user_id: str
    state: str
    language: str
    turn_count: int
    token_usage: dict
    pending_question: dict | None
    error: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SessionDetail(BaseModel):
    session: SessionOut
    messages: list[MessageOut]
    knowledge: KnowledgeOut | None
    procedure_state: str | None
    waiting_for: str | None
    current_step: str | None
    supervisor: dict | None
