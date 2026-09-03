from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin

DATA_SOURCE_KINDS = ("file", "spreadsheet", "email", "web_app", "database", "api", "folder", "other")
SENSITIVITIES = ("none", "internal", "pii", "secret")


class DataSource(IdMixin, TimestampMixin, Base):
    __tablename__ = "data_sources"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    access_notes: Mapped[str | None] = mapped_column(Text)
    schema_def: Mapped[dict] = mapped_column("schema", JSON, default=dict, nullable=False)
    sample_refs: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(16), default="internal", nullable=False)
