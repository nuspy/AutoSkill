from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime

VERSION_STATES = (
    "draft",
    "testing",
    "tested",
    "submitted_for_review",
    "approved",
    "changes_requested",
    "rejected",
    "published",
    "superseded",
    "deprecated",
    "discarded",
)
VERSION_ORIGINS = ("interview", "manual", "improvement", "fork", "trial_corrections", "import")


class SkillVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_skill_version"),)

    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    major: Mapped[int] = mapped_column(Integer, nullable=False)
    minor: Mapped[int] = mapped_column(Integer, nullable=False)
    patch: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="draft", index=True, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    origin: Mapped[str] = mapped_column(String(24), default="interview", nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {"files": [{path, hash, size}]}
    frontmatter: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    knowledge_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    memory_snapshot: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    validation_report: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    signature: Mapped[str | None] = mapped_column(String(128))
    build_log: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(36))  # user id or "system"
    state_changed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    is_current_draft: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class StepDefinition(IdMixin, Base):
    __tablename__ = "step_definitions"
    __table_args__ = (UniqueConstraint("skill_version_id", "key", name="uq_step_key"),)

    skill_version_id: Mapped[str] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="generative", nullable=False)
    side_effects: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    restore_strategy: Mapped[str] = mapped_column(String(24), default="unknown", nullable=False)
    trial_mode: Mapped[str] = mapped_column(String(16), default="simulate", nullable=False)
    requires_explicit_auth: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    inputs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    outputs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    data_source_refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    success_criteria: Mapped[str | None] = mapped_column(Text)
    failure_modes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    network: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mcp_tool_name: Mapped[str | None] = mapped_column(String(80))
    library_component_slug: Mapped[str | None] = mapped_column(String(80))
    test_status: Mapped[str] = mapped_column(String(16), default="untested", nullable=False)
    confirmations_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LibraryComponent(IdMixin, TimestampMixin, Base):
    """Admin-provided ancillary skills and MCP servers users can build on."""

    __tablename__ = "library_components"

    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # skill | mcp_server
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    source: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )  # {type: pip|npm|git_url|package_upload|hub_skill, ...}
    tools: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False
    )  # [{name, description, input_schema, side_effects}]
    env_requirements: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{name, description, secret}]
    install: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )  # {command, args, transport, url, per_target: {...}}
    docs: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    added_by: Mapped[str | None] = mapped_column(String(36))


class SkillDependency(IdMixin, Base):
    __tablename__ = "skill_dependencies"
    __table_args__ = (UniqueConstraint("skill_version_id", "component_slug", name="uq_skill_dep"),)

    skill_version_id: Mapped[str] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    component_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    version_constraint: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
