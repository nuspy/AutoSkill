from __future__ import annotations

from sqlalchemy import Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin


class ProjectUsageDaily(IdMixin, Base):
    __tablename__ = "project_usage_daily"
    __table_args__ = (UniqueConstraint("project_id", "date", "provider_id", name="uq_usage_day"),)

    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    provider_id: Mapped[str | None] = mapped_column(String(36))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
