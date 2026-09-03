from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime, utcnow


class UserRole(enum.StrEnum):
    admin = "admin"
    reviewer = "reviewer"
    member = "member"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.member, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RefreshToken(IdMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=utcnow)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
