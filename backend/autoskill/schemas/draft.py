"""Structured output of the author agent and the version/library API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel


class DraftStep(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)
    title: str = Field(max_length=200)
    instruction: str  # what the agent must do, plain language, imperative
    kind: Literal["deterministic", "generative", "human_gate"] = "generative"
    side_effects: Literal["read_only", "reversible", "irreversible", "unknown"] = "unknown"
    restore_strategy: Literal["none", "backup_file", "db_transaction", "sandbox_copy", "manual", "unknown"] = "unknown"
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    data_source_refs: list[str] = Field(default_factory=list)
    success_criteria: str = ""
    failure_modes: list[str] = Field(default_factory=list)
    network: bool = False
    library_component_slug: str | None = None


class DraftFile(BaseModel):
    path: str = Field(pattern=r"^(references|scripts|assets)/[A-Za-z0-9_.\-/]+$")
    content: str


class DraftDependency(BaseModel):
    component_slug: str
    reason: str = ""


class DraftSpec(BaseModel):
    description: str = Field(min_length=1, max_length=1024)
    compatibility: str | None = Field(default=None, max_length=500)
    overview: str  # markdown, the top of SKILL.md body (purpose, when to use, inputs/outputs)
    steps: list[DraftStep] = Field(min_length=1)
    edge_cases_markdown: str = ""
    files: list[DraftFile] = Field(default_factory=list)
    dependencies: list[DraftDependency] = Field(default_factory=list)
    changelog: str = ""


# --- API schemas --------------------------------------------------------------------


class StepOut(ORMModel):
    id: str
    ordinal: int
    key: str
    title: str
    instruction: str
    kind: str
    side_effects: str
    restore_strategy: str
    trial_mode: str
    requires_explicit_auth: bool
    inputs: list
    outputs: list
    data_source_refs: list
    success_criteria: str | None
    failure_modes: list
    network: bool
    mcp_tool_name: str | None
    library_component_slug: str | None
    test_status: str
    confirmations_count: int


class VersionOut(ORMModel):
    id: str
    skill_id: str
    version: str
    state: str
    parent_version_id: str | None
    origin: str
    manifest: dict
    frontmatter: dict
    changelog: str | None
    rationale: str | None
    validation_report: dict
    signature: str | None
    created_by: str | None
    is_current_draft: bool
    build: int = 1
    state_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VersionDetail(VersionOut):
    steps: list[StepOut] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)
    build_log: str | None = None


class FileContent(BaseModel):
    path: str
    content: str
    size: int
    binary: bool = False


class GenerateRequest(BaseModel):
    mode: Literal["new", "patch"] = "new"
    instructions: str | None = Field(default=None, max_length=8000)
    base_version_id: str | None = None


class InstallDoc(BaseModel):
    target: str
    markdown: str
    bundle_url: str | None = None  # online address of this INSTALL.md (token link or public hub)
    manifest_url: str | None = None
    public: bool = False  # True when the URLs only work for public skills (no download link yet)


class LibraryComponentIn(BaseModel):
    kind: Literal["skill", "mcp_server", "plugin"]
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=4000)
    version: str = Field(default="1.0.0", max_length=32)
    source: dict = Field(default_factory=dict)
    tools: list[dict] = Field(default_factory=list)
    env_requirements: list[dict] = Field(default_factory=list)
    install: dict = Field(default_factory=dict)
    docs: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_enabled: bool = True
    install_paths: dict[str, str] = Field(default_factory=dict)


class LibraryComponentOut(ORMModel):
    id: str
    kind: str
    slug: str
    name: str
    description: str
    version: str
    source: dict
    tools: list
    env_requirements: list
    install: dict
    docs: str | None
    tags: list
    is_enabled: bool
    added_by: str | None
    artifact: dict | None = None
    install_paths: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
