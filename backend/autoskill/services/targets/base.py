from __future__ import annotations

import json
from dataclasses import dataclass, field

from autoskill.prompts import render


@dataclass
class McpServerSpec:
    """What the agent must register: a stdio command or an http url, plus env variable names."""

    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env_requirements: list[dict] = field(default_factory=list)  # [{name, description, secret}]
    description: str = ""
    install_hint: str = ""  # e.g. "pipx install autoskill-local"
    kind: str = "library"  # companion | generated | library
    download_url: str | None = None  # where the agent can fetch the server package (no login)
    sha256: str | None = None
    install_command: str = ""  # full command, e.g. `pipx install https://.../mcp/x-tools.zip`
    docs: str | None = None


@dataclass
class InstallContext:
    skill_name: str
    skill_title: str
    version: str
    server_url: str
    project_slug: str
    mcp_servers: list[McpServerSpec] = field(default_factory=list)
    # catalog skills/plugins: [{slug, name, kind, version, install_hint, download_url, sha256, install_command,
    #                           install_path, docs, env_requirements}]
    dependencies: list[dict] = field(default_factory=list)
    trial: bool = False
    zip_url: str | None = None
    git_url: str | None = None
    # online-reachable install bundle (see services/distribution/bundle.py)
    bundle_url: str | None = None  # this INSTALL.md
    manifest_url: str | None = None  # install.json
    build: int = 1
    companion_wheel_url: str | None = None
    companion_install_command: str = "pipx install autoskill-local"
    artifacts: list[dict] = field(default_factory=list)  # [{name, kind, url, sha256, size}]
    agent_instructions: list[str] = field(default_factory=list)
    trial_session_id: str | None = None
    installed_callback_url: str | None = None
    expires_at: str | None = None

    @property
    def cli_install_command(self) -> str:
        verb = "trial install" if self.trial else "install"
        if self.manifest_url:
            token = " --token <trial-token>" if self.trial else ""
            return f"autoskill {verb} --from {self.manifest_url}{token}"
        return f"autoskill {verb} {self.skill_name}@{self.version} --target <target>"


class TargetAdapter:
    id: str = "base"
    display_name: str = "Agent"
    verified_on: str = "2026-09"
    docs_url: str = ""
    global_skill_dir: str = "~/.agent/skills"
    workspace_skill_dir: str | None = None
    mcp_config_path: str = ""
    mcp_config_format: str = "json"  # json | yaml | toml | cli
    supports_git_install: bool = False

    def skill_install_paths(self) -> list[str]:
        paths = [f"{self.global_skill_dir}/<skill-name>/"]
        if self.workspace_skill_dir:
            paths.append(f"{self.workspace_skill_dir}/<skill-name>/")
        return paths

    def mcp_config_snippet(self, spec: McpServerSpec) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def skill_config_snippet(self, ctx: InstallContext) -> str:
        return ""

    def git_install_command(self, ctx: InstallContext) -> str | None:
        return None

    def render_install_md(self, ctx: InstallContext) -> str:
        return render(
            f"install/{self.id}",
            ctx=ctx,
            adapter=self,
            mcp_snippets=[(m, self.mcp_config_snippet(m)) for m in ctx.mcp_servers],
            skill_config=self.skill_config_snippet(ctx),
            git_command=self.git_install_command(ctx),
        )

    def describe(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "global_skill_dir": self.global_skill_dir,
            "workspace_skill_dir": self.workspace_skill_dir,
            "mcp_config_path": self.mcp_config_path,
            "mcp_config_format": self.mcp_config_format,
            "supports_git_install": self.supports_git_install,
            "verified_on": self.verified_on,
            "docs_url": self.docs_url,
        }

    @staticmethod
    def _env_block(spec: McpServerSpec) -> dict[str, str]:
        return {e["name"]: f"<{e['name']}>" for e in spec.env_requirements}

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, indent=2, ensure_ascii=False)
