from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime


class VersionTransition(IdMixin, Base):
    __tablename__ = "version_transitions"

    skill_version_id: Mapped[str] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(36))  # null = system
    reason: Mapped[str | None] = mapped_column(Text)
    authorization_id: Mapped[str | None] = mapped_column(String(36))
    review_decision_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class ReviewRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "review_requests"

    skill_version_id: Mapped[str] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    mcp_server_version_id: Mapped[str | None] = mapped_column(String(36))
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), default="open", index=True, nullable=False
    )  # open | in_review | decided | withdrawn
    assignee_id: Mapped[str | None] = mapped_column(String(36))
    summary: Mapped[str | None] = mapped_column(Text)
    checklist: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    priority: Mapped[str] = mapped_column(String(8), default="normal", nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class ReviewDecision(IdMixin, Base):
    __tablename__ = "review_decisions"

    review_request_id: Mapped[str] = mapped_column(
        ForeignKey("review_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)  # approved | changes_requested | rejected
    comment: Mapped[str | None] = mapped_column(Text)
    file_comments: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{path, line, text}]
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class Authorization(IdMixin, Base):
    """Human-only authorization for irreversible platform actions (publish, deprecate)."""

    __tablename__ = "authorizations"

    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(36))
    decided_by: Mapped[str] = mapped_column(String(36), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # granted | denied
    comment: Mapped[str | None] = mapped_column(Text)
    checklist: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
