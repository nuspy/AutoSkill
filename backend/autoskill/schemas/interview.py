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


class AgentInterviewStart(BaseModel):
    """Opening a session from the agent. The person then continues in the browser, as always."""

    description: str = Field(min_length=1, max_length=20000)
    title: str | None = Field(default=None, max_length=200)
    project: str | None = None  # id or slug; optional when the person has exactly one
    language: str = Field(default="en", max_length=8)


class AgentInterviewStarted(BaseModel):
    session_id: str
    skill_id: str
    project: str
    session_token: str  # the executor's own key for this session
    url: str  # where the person continues


class HandoffOut(BaseModel):
    """What the browser shows so the person can attach their agent to this session."""

    session_token: str  # shown once
    instruction: str  # ready to paste into the agent


class TurnReply(BaseModel):
    text: str = Field(default="", max_length=20000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    turn_id: int | None = None


class AttachmentOut(BaseModel):
    """A stored file as the interview carries it: `preview` is what the model gets to read."""

    name: str
    media_type: str
    size: int
    hash: str
    preview: str


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
    origin: str = "browser"
    agent_target: str | None = None
    # computed, not columns: whether an executor is attached at all, and whether it is polling now
    agent_attached: bool = False
    agent_live: bool = False
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
    # set while a past step is being re-run: {"from_ordinal", "new_from_ordinal", ...}
    replay: dict | None = None


class StepOut(ORMModel):
    """One execution of a step. `checkpoint` is omitted: it is engine state, not something to show."""

    id: str
    ordinal: int
    key: str
    kind: str
    status: str
    attempt: int
    input: dict
    output: dict
    supervisor_decision: dict | None
    next_key: str | None
    error: str | None
    llm_usage: dict | None
    started_at: datetime
    ended_at: datetime | None
    replayable: bool = False
