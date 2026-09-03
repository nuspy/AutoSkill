from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel


class TrialCreate(BaseModel):
    skill_version_id: str
    target_agent: str
    purpose: Literal["develop", "retest", "hub_evaluate"] = "develop"
    mode: Literal["interactive", "async"] = "interactive"
    device_id: str | None = None
    auto_confirm: bool = True


class TrialPatch(BaseModel):
    auto_confirm: bool | None = None


class TrialOut(ORMModel):
    id: str
    user_id: str
    project_id: str
    device_id: str | None
    skill_id: str
    skill_version_id: str
    purpose: str
    target_agent: str
    mode: str
    auto_confirm: bool = True
    state: str
    build: int
    current_step_key: str | None
    current_iteration: int
    corrections: list
    outcome: str | None
    summary: str | None
    keep_installed: bool | None
    started_at: datetime | None
    suspended_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TrialCreated(TrialOut):
    session_token: str
    cli_command: str
    package_url: str
    bundle_url: str | None = None  # INSTALL.md reachable online without login (download grant)
    manifest_url: str | None = None  # install.json, same grant


class TrialInstalled(BaseModel):
    install_manifest: dict[str, Any] = Field(default_factory=dict)
    build: int | None = None


class TrialOutcomeIn(BaseModel):
    outcome: Literal["accepted", "changes_requested", "removed", "major_rework", "abandoned"]
    keep_installed: bool = False
    note: str | None = Field(default=None, max_length=4000)


class TrialDetail(BaseModel):
    trial: TrialOut
    skill_name: str
    skill_title: str
    version: str
    steps: list[dict]
    runs: list[dict]
    pending_checkpoint: dict | None
    checkpoints: list[dict]
    snapshots: list[dict] = Field(default_factory=list)
    package_url: str
    bundle_url: str | None = None
    manifest_url: str | None = None


# --- telemetry -------------------------------------------------------------------------


class RunStart(BaseModel):
    skill_name: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    skill_version_id: str | None = None
    agent_target: str | None = None
    agent_session_ref: str | None = None
    install_id: str | None = None
    trial_session_token: str | None = None
    inputs_summary: str | None = Field(default=None, max_length=4000)


class RunStartOut(BaseModel):
    run_id: str
    trial_session_id: str | None
    mode: str
    skill_version: str | None


class StepLog(BaseModel):
    step_key: str = Field(max_length=64)
    title: str | None = None
    status: str = "succeeded"
    iteration: int = 1
    execution_mode: str | None = None
    proposed_action: Any = None
    executed_action: Any = None
    inputs: Any = None
    outputs: Any = None
    error: Any = None
    tool_name: str | None = None
    llm_usage: dict | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None


class RunEnd(BaseModel):
    status: Literal["succeeded", "failed", "aborted", "needs_review"]
    summary: str | None = None
    error: Any = None
    llm_usage: dict | None = None


class IssueIn(BaseModel):
    run_id: str | None = None
    skill_name: str | None = None
    skill_id: str | None = None
    step_key: str | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    description: str = Field(min_length=1, max_length=8000)
    evidence: Any = None


class CheckpointIn(BaseModel):
    run_id: str
    step_key: str = Field(max_length=64)
    phase: Literal["explain", "preview", "execute", "verify", "restore"]
    iteration: int | None = None
    execution_mode: str | None = None
    proposal: dict[str, Any] = Field(default_factory=dict)


class CheckpointOut(ORMModel):
    id: str
    run_id: str
    trial_session_id: str | None
    step_key: str
    phase: str
    iteration: int
    execution_mode: str
    state: str
    proposal: dict
    decision: str | None
    correction_text: str | None
    updated_instructions: str | None
    decided_by: str | None
    decided_at: datetime | None
    expires_at: datetime
    created_at: datetime


class DecisionIn(BaseModel):
    decision: Literal[
        "continue", "change", "redo", "skip", "stop", "approve_and_authorize_next", "authorize_execute", "restore"
    ]
    correction_text: str | None = Field(default=None, max_length=8000)
    updated_instructions: str | None = Field(default=None, max_length=8000)


class SnapshotIn(BaseModel):
    run_id: str
    step_key: str = Field(max_length=64)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class SnapshotOut(ORMModel):
    id: str
    run_id: str
    trial_session_id: str | None
    step_key: str
    iteration: int
    items: list
    note: str | None
    taken_at: datetime
    restored_at: datetime | None
    restore_result: dict | None


class DiscussionMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class DiscussionOut(ORMModel):
    id: str
    skill_id: str
    skill_version_id: str
    trial_session_id: str | None
    checkpoint_id: str | None
    step_key: str
    state: str
    outcome: dict | None
    messages: list
    created_at: datetime


class RunOut(ORMModel):
    id: str
    project_id: str
    skill_id: str
    skill_version_id: str | None
    skill_version: str | None
    trial_session_id: str | None
    source: str
    agent_target: str | None
    status: str
    inputs_summary: str | None
    summary: str | None
    error: dict | None
    llm_usage: dict
    human_feedback: str | None
    is_golden: bool
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None


class RunStepOut(ORMModel):
    id: str
    ordinal: int
    step_key: str
    title: str | None
    status: str
    iteration: int
    execution_mode: str | None
    proposed_action: Any
    executed_action: Any
    human_correction: Any
    inputs: Any
    outputs: Any
    error: Any
    tool_name: str | None
    llm_usage: dict | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    created_at: datetime


class RunDetail(BaseModel):
    run: RunOut
    steps: list[RunStepOut]
    checkpoints: list[CheckpointOut]
    annotations: list[dict]


class RunFeedback(BaseModel):
    human_feedback: Literal["ok", "corrected", "wrong"] | None = None
    is_golden: bool | None = None
