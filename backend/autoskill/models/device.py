from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime


class Device(IdMixin, TimestampMixin, Base):
    """A user's machine registered by the local CLI."""

    __tablename__ = "devices"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    os: Mapped[str | None] = mapped_column(String(80))
    agent_targets: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cli_version: Mapped[str | None] = mapped_column(String(40))
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class DeviceAuthorization(IdMixin, Base):
    """OAuth-style device-code flow state for `autoskill login`."""

    __tablename__ = "device_authorizations"

    device_code_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    user_code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    device_name: Mapped[str] = mapped_column(String(120), nullable=False)
    device_os: Mapped[str | None] = mapped_column(String(80))
    agent_targets: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    api_key_id: Mapped[str | None] = mapped_column(String(36))
    issued_key: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
