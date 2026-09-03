from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class McpRegistration:
    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)


class LocalTarget:
    """Base adapter. Subclasses define paths and the MCP config file format."""

    id = "base"
    display_name = "Agent"
    skill_dir_rel = ".agent/skills"
    mcp_config_rel = ".agent/mcp.json"
    detect_rel: tuple[str, ...] = ()

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home) if home else Path.home()

    # --- paths -------------------------------------------------------------------------
    @property
    def skill_dir(self) -> Path:
        return self.home / self.skill_dir_rel

    @property
    def mcp_config(self) -> Path:
        return self.home / self.mcp_config_rel

    def detect(self) -> bool:
        return any((self.home / rel).exists() for rel in self.detect_rel) or self.skill_dir.exists()

    # --- skills ------------------------------------------------------------------------
    def install_skill(self, package_dir: Path, skill_name: str) -> dict[str, Any]:
        dest = self.skill_dir / skill_name
        backup = None
        if dest.exists():
            backup = dest.with_name(f".{skill_name}.autoskill-backup")
            if backup.exists():
                shutil.rmtree(backup)
            dest.rename(backup)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package_dir, dest)
        return {"skill_dir": str(dest), "backup_dir": str(backup) if backup else None}

    def remove_skill(self, skill_name: str, manifest: dict[str, Any] | None = None) -> None:
        dest = Path((manifest or {}).get("skill_dir") or (self.skill_dir / skill_name))
        if dest.exists():
            shutil.rmtree(dest)
        backup = (manifest or {}).get("backup_dir")
        if backup and Path(backup).exists():
            Path(backup).rename(dest)

    # --- MCP registration --------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        if not self.mcp_config.exists():
            return {}
        return self._parse(self.mcp_config.read_text())

    def _store(self, data: dict[str, Any]) -> None:
        self.mcp_config.parent.mkdir(parents=True, exist_ok=True)
        self.mcp_config.write_text(self._dump(data))

    def _parse(self, text: str) -> dict[str, Any]:
        return json.loads(text) if text.strip() else {}

    def _dump(self, data: dict[str, Any]) -> str:
        return json.dumps(data, indent=2) + "\n"

    root_key = "mcpServers"

    def _entry(self, reg: McpRegistration) -> dict[str, Any]:
        entry: dict[str, Any] = {"url": reg.url} if reg.url else {"command": reg.command, "args": reg.args}
        if reg.env and not reg.url:
            entry["env"] = reg.env
        return entry

    def register_mcp(self, reg: McpRegistration) -> dict[str, Any]:
        data = self._load()
        servers = data.setdefault(self.root_key, {})
        previous = servers.get(reg.name)
        servers[reg.name] = self._entry(reg)
        self._store(data)
        return {"config": str(self.mcp_config), "name": reg.name, "previous": previous}

    def unregister_mcp(self, name: str, previous: dict[str, Any] | None = None) -> None:
        data = self._load()
        servers = data.get(self.root_key, {})
        if previous is not None:
            servers[name] = previous
        else:
            servers.pop(name, None)
        self._store(data)

    def registered_mcps(self) -> dict[str, Any]:
        return dict(self._load().get(self.root_key, {}))
