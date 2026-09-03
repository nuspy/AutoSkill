from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime

MEMORY_KINDS = (
    "rationale",
    "business_need",
    "human_procedure",
    "technical_note",
    "integration_note",
    "data_note",
    "decision",
    "lesson_learned",
)
MEMORY_SOURCES = ("interview", "trial_discussion", "manual", "improvement", "import")
MEMORY_STATUSES = ("active", "superseded", "archived", "proposed")


class SkillMemoryEntry(IdMixin, TimestampMixin, Base):
    """Append-only memory about a skill: rationale, business needs, procedures, integrations."""

    __tablename__ = "skill_memory_entries"

    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    structured: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    step_key: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(36))
    skill_version_id: Mapped[str | None] = mapped_column(String(36))
    author_user_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True, nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(String(36))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime)
