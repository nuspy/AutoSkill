from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime

PROCEDURE_STATES = ("running", "waiting_human", "completed", "failed", "cancelled")
STEP_KINDS = ("code", "llm", "supervisor", "human_auth")


class Procedure(IdMixin, TimestampMixin, Base):
    """A deterministic, resumable procedure instance (interview, trial step, publish...)."""

    __tablename__ = "procedures"

    kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(32))
    subject_id: Mapped[str | None] = mapped_column(String(36), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    current_step_key: Mapped[str | None] = mapped_column(String(64))
    waiting_for: Mapped[str | None] = mapped_column(String(64))
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class ProcedureStep(IdMixin, Base):
    __tablename__ = "procedure_steps"

    procedure_id: Mapped[str] = mapped_column(
        ForeignKey("procedures.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # succeeded | failed | waiting
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    supervisor_decision: Mapped[dict | None] = mapped_column(JSON)
    next_key: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    llm_usage: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime)
