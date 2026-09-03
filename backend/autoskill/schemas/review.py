from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel


class SubmitReview(BaseModel):
    summary: str | None = Field(default=None, max_length=8000)


class ReviewRequestOut(ORMModel):
    id: str
    skill_version_id: str
    skill_id: str
    project_id: str
    requested_by: str
    state: str
    assignee_id: str | None
    summary: str | None
    checklist: dict
    priority: str
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewDecisionOut(ORMModel):
    id: str
    review_request_id: str
    reviewer_id: str
    decision: str
    comment: str | None
    file_comments: list
    created_at: datetime


class ReviewQueueItem(ReviewRequestOut):
    skill_title: str = ""
    skill_name: str = ""
    version: str = ""
    requested_by_name: str = ""


class ReviewBundle(BaseModel):
    request: ReviewRequestOut
    skill_title: str
    skill_name: str
    version: str
    version_id: str
    previous_version: str | None
    diff: dict
    files: list[dict]
    decisions: list[ReviewDecisionOut]
    memory_count: int


class DecisionIn(BaseModel):
    decision: Literal["approved", "changes_requested", "rejected"]
    comment: str | None = Field(default=None, max_length=8000)
    file_comments: list[dict] = Field(default_factory=list)


class AuthorizeIn(BaseModel):
    action: Literal["publish", "deprecate"]
    checklist: dict[str, bool] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=4000)


class AuthorizationOut(ORMModel):
    id: str
    project_id: str
    subject_type: str
    subject_id: str
    action: str
    requested_by: str | None
    decided_by: str
    decision: str
    comment: str | None
    checklist: dict
    created_at: datetime


class TransitionOut(ORMModel):
    id: str
    skill_version_id: str
    from_state: str
    to_state: str
    actor_user_id: str | None
    reason: str | None
    authorization_id: str | None
    review_decision_id: str | None
    created_at: datetime


class TransitionIn(BaseModel):
    to_state: Literal["testing", "tested", "discarded"]
    reason: str | None = Field(default=None, max_length=2000)
