from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime

SCOPE_TELEMETRY_WRITE = "telemetry:write"
SCOPE_TRIAL_CLIENT = "trial:client"
SCOPE_RUNS_READ = "runs:read"
ALL_SCOPES = {SCOPE_TELEMETRY_WRITE, SCOPE_TRIAL_CLIENT, SCOPE_RUNS_READ}


class ApiKey(IdMixin, TimestampMixin, Base):
    """API key owned either by a project (telemetry) or by a user (CLI/device)."""

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
