from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(String(2000))
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[str | None] = mapped_column(String(36))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class NotificationPreference(IdMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_notification_pref"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
