"""Install bundle: the machine-readable description of everything an agent needs to install a skill.

Served as `install.json` next to `INSTALL.<target>.md` at an online-reachable URL (see api/dl.py). Every
artifact referenced here is downloadable from the URL given, with no login, while the bundle is valid.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BUNDLE_FORMAT = "autoskill-install/1"


class ArtifactRef(BaseModel):
    url: str
    filename: str
    sha256: str | None = None
    size: int | None = None
    content_type: str = "application/zip"


class EnvRequirement(BaseModel):
    name: str
    description: str = ""
    secret: bool = False


class InstallMethod(BaseModel):
    """How to get the component onto the machine (before registering it)."""

    method: Literal["pipx_archive", "pipx", "pip", "npm", "git", "copy", "binary", "manual", "none"] = "manual"
    command: str = ""  # shell command a person or an agent can run
    spec: str | None = None  # pip/npm spec, git url, or download url
    notes: str = ""


class McpRegistration(BaseModel):
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env_requirements: list[EnvRequirement] = Field(default_factory=list)


class McpServerEntry(BaseModel):
    name: str
    kind: Literal["companion", "generated", "library"]
    description: str = ""
    version: str | None = None
    download: ArtifactRef | None = None
    install: InstallMethod = Field(default_factory=InstallMethod)
    registration: McpRegistration = Field(default_factory=McpRegistration)
    snippets: dict[str, str] = Field(default_factory=dict)  # target id -> config snippet
    tools: list[dict] = Field(default_factory=list)
    docs: str | None = None


class ComponentEntry(BaseModel):
    """A catalog skill or plugin the skill depends on (MCP components are listed in mcp_servers)."""

    slug: str
    kind: Literal["skill", "plugin"]
    name: str
    version: str
    description: str = ""
    reason: str = ""
    download: ArtifactRef | None = None
    install: InstallMethod = Field(default_factory=InstallMethod)
    install_paths: dict[str, str] = Field(default_factory=dict)  # target id -> destination folder
    env_requirements: list[EnvRequirement] = Field(default_factory=list)
    docs: str | None = None


class SkillEntry(BaseModel):
    skill_id: str
    version_id: str
    name: str
    title: str
    version: str
    build: int = 1
    description: str = ""
    download: ArtifactRef
    git_url: str | None = None
    signature: str | None = None
    files: list[dict] = Field(default_factory=list)  # [{path, hash, size}] of the skill folder
    install_paths: dict[str, list[str]] = Field(default_factory=dict)  # target id -> candidate folders


class CompanionEntry(BaseModel):
    package: str = "autoskill-local"
    version: str | None = None
    wheel: ArtifactRef | None = None
    pip_spec: str = "autoskill-local"
    install_command: str = "pipx install autoskill-local"
    command: str = "autoskill-companion"
    env_requirements: list[EnvRequirement] = Field(default_factory=list)


class TrialEntry(BaseModel):
    session_id: str
    mode: str
    purpose: str
    target_agent: str
    installed_callback_url: str
    header_name: str = "X-AutoSkill-Trial"
    note: str = (
        "The trial session token is NOT in this file: it is given to the person in the AutoSkill UI. "
        "Put it in the companion env as AUTOSKILL_SESSION_TOKEN and send it as X-AutoSkill-Trial when "
        "calling installed_callback_url."
    )


class InstallBundle(BaseModel):
    format: str = BUNDLE_FORMAT
    kind: Literal["trial", "version", "hub"]
    server_url: str
    bundle_url: str  # this bundle's INSTALL.md
    manifest_url: str  # this file
    install_md_urls: dict[str, str] = Field(default_factory=dict)  # target id -> INSTALL.<target>.md
    generated_at: datetime
    expires_at: datetime | None = None
    default_target: str = "hermes"
    targets: list[str] = Field(default_factory=list)
    skill: SkillEntry
    companion: CompanionEntry
    mcp_servers: list[McpServerEntry] = Field(default_factory=list)
    components: list[ComponentEntry] = Field(default_factory=list)
    trial: TrialEntry | None = None
    agent_instructions: list[str] = Field(default_factory=list)

    def artifacts(self) -> list[dict]:
        """Everything downloadable, for the INSTALL.md table."""
        rows = [{"name": f"{self.skill.name} (skill)", "kind": "skill", **self.skill.download.model_dump()}]
        if self.companion.wheel:
            rows.append({"name": self.companion.package, "kind": "companion", **self.companion.wheel.model_dump()})
        for m in self.mcp_servers:
            if m.download and m.kind != "companion":
                rows.append({"name": m.name, "kind": f"mcp ({m.kind})", **m.download.model_dump()})
        for c in self.components:
            if c.download:
                rows.append({"name": c.name, "kind": c.kind, **c.download.model_dump()})
        return rows


class DownloadLinkIn(BaseModel):
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    label: str | None = Field(default=None, max_length=120)
    target_agent: str | None = None


class DownloadLinkOut(BaseModel):
    id: str
    kind: str
    label: str | None
    target_agent: str | None
    bundle_url: str
    manifest_url: str
    expires_at: datetime | None
    revoked_at: datetime | None
    download_count: int
    last_used_at: datetime | None
    created_at: datetime
