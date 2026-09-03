from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin

MCP_STATES = ("draft", "built", "trial_passed", "trial_failed", "approved", "published", "deprecated")


class McpServer(IdMixin, TimestampMixin, Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("skill_id", name="uq_mcp_server_skill"),)

    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)  # <skill>-tools
    runtime: Mapped[str] = mapped_column(String(24), default="python-mcp", nullable=False)


class McpServerVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_versions"
    __table_args__ = (UniqueConstraint("skill_version_id", name="uq_mcp_version_skill_version"),)

    mcp_server_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_version_id: Mapped[str] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tools: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False
    )  # [{name, step_key, description, side_effects, input_schema}]
    env_requirements: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    dependencies: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # pip packages
    draft_spec: Mapped[dict | None] = mapped_column(JSON)
    build_log: Mapped[str | None] = mapped_column(Text)
    static_report: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trial_report: Mapped[dict | None] = mapped_column(JSON)
    build: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
