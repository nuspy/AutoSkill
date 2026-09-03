from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime

INTERVIEW_STATES = (
    "created",
    "intake",
    "exploring",
    "gating",
    "awaiting_answer",
    "awaiting_confirmation",
    "complete",
    "drafting_requested",
    "abandoned",
    "failed",
)


class InterviewSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "interview_sessions"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    knowledge_id: Mapped[str | None] = mapped_column(String(36))
    procedure_id: Mapped[str | None] = mapped_column(String(36))
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_usage: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    pending_question: Mapped[dict | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    error: Mapped[str | None] = mapped_column(Text)


class InterviewMessage(IdMixin, Base):
    __tablename__ = "interview_messages"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class KnowledgeDoc(IdMixin, Base):
    __tablename__ = "knowledge_docs"

    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    doc: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    completeness: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    derived_from_session_id: Mapped[str | None] = mapped_column(String(36))
    frozen: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
