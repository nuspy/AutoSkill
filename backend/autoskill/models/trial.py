from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime

TRIAL_STATES = (
    "requested",
    "installing",
    "installed",
    "testing",
    "suspended",
    "reviewing",
    "decided",
    "removed",
    "abandoned",
)
TRIAL_PURPOSES = ("develop", "retest", "hub_evaluate")
TRIAL_OUTCOMES = ("accepted", "changes_requested", "removed", "major_rework", "abandoned")
CHECKPOINT_PHASES = ("explain", "preview", "execute", "verify", "restore")
DECISIONS = (
    "continue",
    "change",
    "redo",
    "skip",
    "stop",
    "approve_and_authorize_next",
    "authorize_execute",
    "restore",
)


class TrialSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "trial_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(36))
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_version_id: Mapped[str] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(16), default="develop", nullable=False)
    target_agent: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="interactive", nullable=False)
    # skip checkpoints of deterministic steps already confirmed N times (setting auto_confirm_after_confirmations)
    auto_confirm: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="requested", index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    build: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # bumps when the package changes
    install_manifest: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    current_step_key: Mapped[str | None] = mapped_column(String(64))
    current_iteration: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    corrections: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{step_key, text, at}]
    outcome: Mapped[str | None] = mapped_column(String(24))
    summary: Mapped[str | None] = mapped_column(Text)
    keep_installed: Mapped[bool | None] = mapped_column(Boolean)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    suspended_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class Run(IdMixin, TimestampMixin, Base):
    __tablename__ = "runs"

    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    skill_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    skill_version: Mapped[str | None] = mapped_column(String(32))
    trial_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    source: Mapped[str] = mapped_column(String(16), default="production", nullable=False)  # trial | production | import
    agent_target: Mapped[str | None] = mapped_column(String(32))
    device_id: Mapped[str | None] = mapped_column(String(36))
    installation_id: Mapped[str | None] = mapped_column(String(36))
    user_id: Mapped[str | None] = mapped_column(String(36))
    api_key_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="running", index=True, nullable=False)
    inputs_summary: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict | None] = mapped_column(JSON)
    llm_usage: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    human_feedback: Mapped[str | None] = mapped_column(String(16))  # ok | corrected | wrong
    is_golden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class RunStep(IdMixin, Base):
    __tablename__ = "run_steps"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    execution_mode: Mapped[str | None] = mapped_column(String(16))
    proposed_action: Mapped[dict | None] = mapped_column(JSON)
    executed_action: Mapped[dict | None] = mapped_column(JSON)
    human_correction: Mapped[dict | None] = mapped_column(JSON)
    inputs: Mapped[dict | None] = mapped_column(JSON)
    outputs: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)
    tool_name: Mapped[str | None] = mapped_column(String(120))
    llm_usage: Mapped[dict | None] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class Checkpoint(IdMixin, Base):
    __tablename__ = "checkpoints"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False)
    trial_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), default="simulated", nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True, nullable=False)
    proposal: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    decision: Mapped[str | None] = mapped_column(String(32))
    correction_text: Mapped[str | None] = mapped_column(Text)
    updated_instructions: Mapped[str | None] = mapped_column(Text)
    confirmation_token: Mapped[str | None] = mapped_column(String(64))
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class StepDiscussion(IdMixin, TimestampMixin, Base):
    __tablename__ = "step_discussions"

    skill_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    skill_version_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    trial_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    checkpoint_id: Mapped[str | None] = mapped_column(String(36), index=True)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    outcome: Mapped[dict | None] = mapped_column(JSON)
    messages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{role, content, at, proposal?}]


class RunAnnotation(IdMixin, Base):
    __tablename__ = "run_annotations"

    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    run_step_id: Mapped[str | None] = mapped_column(String(36))
    skill_id: Mapped[str | None] = mapped_column(String(36), index=True)
    step_key: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(16), default="note", nullable=False)  # note | root_cause | label | issue
    severity: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class TrialSnapshot(IdMixin, Base):
    """What the agent backed up before a step with real effects, so the person can order a restore."""

    __tablename__ = "trial_snapshots"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False)
    trial_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    items: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{kind, ref, local_copy?, note?}]
    note: Mapped[str | None] = mapped_column(Text)
    taken_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    restored_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    restore_result: Mapped[dict | None] = mapped_column(JSON)
