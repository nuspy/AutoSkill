from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TZDateTime, utcnow


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_api_key_id: Mapped[str | None] = mapped_column(String(36))
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[str | None] = mapped_column(String(36), index=True)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, nullable=False)
