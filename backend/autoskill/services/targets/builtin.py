from __future__ import annotations

import yaml

from autoskill.services.targets.base import InstallContext, McpServerSpec, TargetAdapter


class HermesAdapter(TargetAdapter):
    id = "hermes"
    display_name = "Hermes Agent"
    docs_url = "https://hermes-agent.nousresearch.com/docs/user-guide/configuration"
    global_skill_dir = "~/.hermes/skills"
    mcp_config_path = "~/.hermes/config.yaml"
    mcp_config_format = "yaml"

    def mcp_config_snippet(self, spec: McpServerSpec) -> str:
        entry: dict = (
            {"type": "http", "url": spec.url}
            if spec.url
            else {"type": "stdio", "command": spec.command, "args": spec.args}
        )
        if spec.env_requirements and not spec.url:
            entry["env"] = self._env_block(spec)
        return yaml.safe_dump({"mcp_servers": {spec.name: entry}}, sort_keys=False)

    def skill_config_snippet(self, ctx: InstallContext) -> str:
        return yaml.safe_dump(
            {"skills": {"config": {ctx.skill_name.replace("-", "_"): {"autoskill_server": ctx.server_url}}}},
            sort_keys=False,
        )


class OpenClawAdapter(TargetAdapter):
    id = "openclaw"
    display_name = "OpenClaw"
    docs_url = "https://docs.openclaw.ai/tools/skills-config"
    global_skill_dir = "~/.openclaw/skills"
    workspace_skill_dir = "<workspace>/skills"
    mcp_config_path = "~/.openclaw/skills/config/mcporter.json"
    mcp_config_format = "json"
    supports_git_install = True

    def mcp_config_snippet(self, spec: McpServerSpec) -> str:
        entry: dict = {"url": spec.url} if spec.url else {"command": spec.command, "args": spec.args}
        if spec.env_requirements and not spec.url:
            entry["env"] = self._env_block(spec)
        return self._json({"mcpServers": {spec.name: entry}})

    def git_install_command(self, ctx: InstallContext) -> str | None:
        if not ctx.git_url:
            return None
        return f"openclaw skills install git:{ctx.git_url}@v{ctx.version}"


class ClaudeCodeAdapter(TargetAdapter):
    id = "claude_code"
    display_name = "Claude Code"
    docs_url = "https://code.claude.com/docs"
    global_skill_dir = "~/.claude/skills"
    workspace_skill_dir = "<workspace>/.claude/skills"
    mcp_config_path = "<workspace>/.mcp.json"
    mcp_config_format = "json"

    def mcp_config_snippet(self, spec: McpServerSpec) -> str:
        entry: dict = {"type": "http", "url": spec.url} if spec.url else {"command": spec.command, "args": spec.args}
        if spec.env_requirements and not spec.url:
            entry["env"] = self._env_block(spec)
        return self._json({"mcpServers": {spec.name: entry}})


class CodexAdapter(TargetAdapter):
    id = "codex"
    display_name = "OpenAI Codex"
    docs_url = "https://github.com/openai/codex"
    global_skill_dir = "~/.codex/skills"
    mcp_config_path = "~/.codex/config.toml"
    mcp_config_format = "toml"

    def mcp_config_snippet(self, spec: McpServerSpec) -> str:
        lines = [f"[mcp_servers.{spec.name}]"]
        if spec.url:
            lines.append(f'url = "{spec.url}"')
        else:
            lines.append(f'command = "{spec.command}"')
            args = ", ".join(f'"{a}"' for a in spec.args)
            lines.append(f"args = [{args}]")
            if spec.env_requirements:
                lines.append("")
                lines.append(f"[mcp_servers.{spec.name}.env]")
                for e in spec.env_requirements:
                    lines.append(f'{e["name"]} = "<{e["name"]}>"')
        return "\n".join(lines) + "\n"


class AntigravityAdapter(TargetAdapter):
    id = "antigravity"
    display_name = "Google Antigravity"
    docs_url = "https://antigravity.google/docs/skills"
    global_skill_dir = "~/.gemini/config/skills"
    workspace_skill_dir = "<workspace>/.agents/skills"
    mcp_config_path = "~/.gemini/antigravity/mcp_config.json"  # same file the AutoSkill CLI writes
    mcp_config_format = "json"

    def mcp_config_snippet(self, spec: McpServerSpec) -> str:
        entry: dict = {"url": spec.url} if spec.url else {"command": spec.command, "args": spec.args}
        if spec.env_requirements and not spec.url:
            entry["env"] = self._env_block(spec)
        return self._json({"mcpServers": {spec.name: entry}})


ADAPTERS: dict[str, TargetAdapter] = {
    a.id: a for a in (HermesAdapter(), OpenClawAdapter(), ClaudeCodeAdapter(), CodexAdapter(), AntigravityAdapter())
}
