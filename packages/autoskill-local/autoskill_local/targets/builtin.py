from __future__ import annotations

from typing import Any

import tomlkit
import yaml

from autoskill_local.targets.base import LocalTarget, McpRegistration


class Hermes(LocalTarget):
    id = "hermes"
    display_name = "Hermes Agent"
    skill_dir_rel = ".hermes/skills"
    mcp_config_rel = ".hermes/config.yaml"
    detect_rel = (".hermes",)
    root_key = "mcp_servers"

    def _parse(self, text: str) -> dict[str, Any]:
        return yaml.safe_load(text) or {}

    def _dump(self, data: dict[str, Any]) -> str:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def _entry(self, reg: McpRegistration) -> dict[str, Any]:
        if reg.url:
            return {"type": "http", "url": reg.url}
        entry: dict[str, Any] = {"type": "stdio", "command": reg.command, "args": reg.args}
        if reg.env:
            entry["env"] = reg.env
        return entry


class OpenClaw(LocalTarget):
    id = "openclaw"
    display_name = "OpenClaw"
    skill_dir_rel = ".openclaw/skills"
    mcp_config_rel = ".openclaw/skills/config/mcporter.json"
    detect_rel = (".openclaw",)


class ClaudeCode(LocalTarget):
    id = "claude_code"
    display_name = "Claude Code"
    skill_dir_rel = ".claude/skills"
    mcp_config_rel = ".claude.json"
    detect_rel = (".claude",)

    def _entry(self, reg: McpRegistration) -> dict[str, Any]:
        if reg.url:
            return {"type": "http", "url": reg.url}
        entry: dict[str, Any] = {"type": "stdio", "command": reg.command, "args": reg.args}
        if reg.env:
            entry["env"] = reg.env
        return entry


class Codex(LocalTarget):
    id = "codex"
    display_name = "OpenAI Codex"
    skill_dir_rel = ".codex/skills"
    mcp_config_rel = ".codex/config.toml"
    detect_rel = (".codex",)
    root_key = "mcp_servers"

    def _parse(self, text: str) -> dict[str, Any]:
        return tomlkit.parse(text).unwrap() if text.strip() else {}

    def _dump(self, data: dict[str, Any]) -> str:
        return tomlkit.dumps(data)

    def _entry(self, reg: McpRegistration) -> dict[str, Any]:
        if reg.url:
            return {"url": reg.url}
        entry: dict[str, Any] = {"command": reg.command, "args": reg.args}
        if reg.env:
            entry["env"] = reg.env
        return entry


class Antigravity(LocalTarget):
    id = "antigravity"
    display_name = "Google Antigravity"
    skill_dir_rel = ".gemini/config/skills"
    mcp_config_rel = ".gemini/antigravity/mcp_config.json"
    detect_rel = (".gemini",)


TARGETS: dict[str, type[LocalTarget]] = {t.id: t for t in (Hermes, OpenClaw, ClaudeCode, Codex, Antigravity)}
