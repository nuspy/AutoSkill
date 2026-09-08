from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
import yaml

from autoskill_local.targets.base import LocalTarget, McpRegistration


class Hermes(LocalTarget):
    """Hermes keeps everything under one application directory, not a dotfolder in $HOME.

    `~/.hermes` was the old assumption and it was wrong on this platform, where Hermes lives under
    `AppData/Local/hermes` and sets `HERMES_HOME` to say so. The dotfolder stays last in the list so
    an installation that really does use it keeps working.
    """

    id = "hermes"
    display_name = "Hermes Agent"
    bases = ("AppData/Local/hermes", ".local/share/hermes", ".hermes")
    home_env = "HERMES_HOME"
    skill_dir_rel = "skills"
    mcp_config_rel = "config.yaml"
    root_key = "mcp_servers"
    # Verified on a real installation: `hermes acp --check` answers "Hermes ACP check OK", and the
    # ACP handshake returns agentInfo hermes-agent 0.21.0 with session capabilities. `-z` runs one
    # prompt and exits.
    exe_names = ("hermes",)
    exe_rel = ("hermes-agent/venv/Scripts/hermes.exe", "hermes-agent/venv/bin/hermes")
    acp_args = ("acp",)
    oneshot_args = ("-z", "{prompt}")
    # `hermes -m MODEL --provider PROVIDER` overrides the model for one run (verified in `hermes --help`:
    # "Model override for this invocation"). They are global flags, so they go before the subcommand.
    model_flag = "-m"
    provider_flag = "--provider"

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
    bases = (".openclaw",)
    skill_dir_rel = "skills"
    mcp_config_rel = "skills/config/mcporter.json"


class ClaudeCode(LocalTarget):
    id = "claude_code"
    display_name = "Claude Code"
    bases = (".claude",)
    home_env = "CLAUDE_CONFIG_DIR"
    skill_dir_rel = "skills"
    # `claude -p "..."` answers and exits; verified. No ACP mode as of this writing.
    exe_names = ("claude",)
    oneshot_args = ("-p", "{prompt}")

    @property
    def mcp_config(self) -> Path:
        # The one file that is not under the agent's own directory: it sits beside it, in $HOME.
        return self.home / ".claude.json"

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
    bases = (".codex",)
    home_env = "CODEX_HOME"
    skill_dir_rel = "skills"
    # `codex exec` is its documented non-interactive form. Nothing is declared for OpenClaw or
    # Antigravity: neither was verified here, and a wrong guess would launch the wrong program.
    exe_names = ("codex",)
    oneshot_args = ("exec", "{prompt}")
    mcp_config_rel = "config.toml"
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
    bases = (".gemini",)
    skill_dir_rel = "config/skills"
    mcp_config_rel = "antigravity/mcp_config.json"


TARGETS: dict[str, type[LocalTarget]] = {t.id: t for t in (Hermes, OpenClaw, ClaudeCode, Codex, Antigravity)}
