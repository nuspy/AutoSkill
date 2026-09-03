from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime

PROPOSAL_STATES = ("analyzing", "proposed", "under_review", "accepted", "rejected", "superseded", "failed")
TRIGGERS = ("auto_failure_threshold", "issue_reports", "manual", "scheduled")


class ImprovementProposal(IdMixin, TimestampMixin, Base):
    """A proposed new version derived from failed runs, issues and trial corrections. Never auto-published."""

    __tablename__ = "improvement_proposals"

    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    base_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposed_version_id: Mapped[str | None] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(16), default="analyzing", index=True, nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    source_run_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source_issue_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {clusters: [...], hypotheses: [...]}
    rationale: Mapped[str | None] = mapped_column(Text)
    diff_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    golden_pass_rate: Mapped[float | None] = mapped_column(Float)
    requested_by: Mapped[str | None] = mapped_column(String(36))
    reviewer_id: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    decision_comment: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
