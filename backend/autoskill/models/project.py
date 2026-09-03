from __future__ import annotations

import enum

from sqlalchemy import JSON, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoskill.db.base import Base, IdMixin, TimestampMixin


class ProjectRole(enum.StrEnum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    default_provider_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    members: Mapped[list[ProjectMember]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role"), default=ProjectRole.editor, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="members")
