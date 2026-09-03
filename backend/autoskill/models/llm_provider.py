from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin

ADAPTERS = ("openai_compat", "anthropic", "openai", "google", "openrouter")
PURPOSES = ("interviewer", "author", "coach", "analyst", "supervisor")


class LlmProvider(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_providers"

    scope: Mapped[str] = mapped_column(String(16), default="system", nullable=False)  # system | project
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    models: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(String(2000))
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    purposes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    health: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
