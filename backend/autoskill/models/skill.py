from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime

VISIBILITIES = ("private", "shared", "public")
DEVELOPMENT_STATES = ("active", "suspended", "archived")


class Skill(IdMixin, TimestampMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_skill_project_name"),)

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)  # Agent Skills spec name
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16), default="private", nullable=False)
    development_state: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    suspended_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    suspend_note: Mapped[str | None] = mapped_column(Text)
    current_published_version_id: Mapped[str | None] = mapped_column(String(36))
    latest_version_id: Mapped[str | None] = mapped_column(String(36))
    forked_from_skill_id: Mapped[str | None] = mapped_column(String(36))
    forked_from_version_id: Mapped[str | None] = mapped_column(String(36))
    fork_kind: Mapped[str | None] = mapped_column(String(24))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    install_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime)
