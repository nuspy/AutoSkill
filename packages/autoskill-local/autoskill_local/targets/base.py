from __future__ import annotations

import json
import os
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
    """Base adapter. Subclasses say where the agent lives and how its MCP config is written.

    An agent's directory is **found, not assumed**, because installations differ from machine to
    machine. Assuming cost a whole evening once: Hermes was taken to live in `~/.hermes`, while on
    this platform it actually lives under `AppData/Local/hermes`. Detection therefore never saw it,
    the dashboard offered a target list missing the very agent in use, and installing "for Hermes"
    *created* `~/.hermes` and put the skill there — a directory Hermes has never once read. Every step
    reported success; the skill simply lived where nobody would look.

    Resolution order, most explicit first:

    1. `home=` passed to the constructor — an instruction from the caller, and nothing may override it
       (a test with a temporary home must never reach the real installation, which is exactly how a
       test suite once wrote into somebody's live agent configuration);
    2. `home_dir=`, what the person put in their own AutoSkill config for this agent;
    3. the agent's own environment variable, when the caller asked for no particular home;
    4. the first of `bases` that exists on disk;
    5. failing all of that, `bases[0]` — where a fresh installation would go.
    """

    id = "base"
    display_name = "Agent"
    # Home-relative directories this agent is known to live in, best first.
    bases: tuple[str, ...] = (".agent",)
    # An environment variable the agent itself sets to say where it lives, when it has one.
    home_env: str | None = None
    # Both are relative to the resolved base directory.
    skill_dir_rel = "skills"
    mcp_config_rel = "mcp.json"

    # --- how this agent can be asked to do something -------------------------------------------
    #
    # Declared rather than guessed, and verified per agent. An adapter that says nothing here is not
    # broken: it means the person is told what to paste, which is how every agent worked until now
    # and has to keep working.
    #
    # `exe_names` are looked for on PATH first and inside `base` second, because an agent installed
    # by its own installer is often not on PATH at all.
    exe_names: tuple[str, ...] = ()
    exe_rel: tuple[str, ...] = ()  # paths inside `base` worth trying, best first
    acp_args: tuple[str, ...] = ()  # a JSON-RPC session over stdio: the turns can be watched
    oneshot_args: tuple[str, ...] = ()  # "{prompt}" is replaced; one answer, no session to watch

    def __init__(self, home: Path | None = None, home_dir: str | Path | None = None) -> None:
        self.home = Path(home) if home else Path.home()
        self._home_dir = Path(home_dir) if home_dir else None
        # Discovery is a hint and must never outrank an explicit instruction.
        self._may_discover = home is None

    # --- paths -------------------------------------------------------------------------
    @property
    def base(self) -> Path:
        if self._home_dir is not None:
            return self._home_dir
        if self._may_discover and self.home_env:
            told = os.environ.get(self.home_env)
            if told:
                return Path(told)
        for rel in self.bases:
            if (self.home / rel).exists():
                return self.home / rel
        return self.home / self.bases[0]

    @property
    def base_source(self) -> str:
        """How the directory above was decided, so a wrong guess can be seen instead of inferred.

        `detect()` answers yes or no; it never says *where it looked*. When an agent is installed
        somewhere unusual the two failures look identical from outside — nothing found, and nothing
        found in the wrong place — and only this distinguishes them.
        """
        if self._home_dir is not None:
            return "configured"
        if self._may_discover and self.home_env and os.environ.get(self.home_env):
            return f"${self.home_env}"
        for rel in self.bases:
            if (self.home / rel).exists():
                return "found"
        return "assumed"

    @property
    def skill_dir(self) -> Path:
        return self.base / self.skill_dir_rel

    @property
    def mcp_config(self) -> Path:
        return self.base / self.mcp_config_rel

    def detect(self) -> bool:
        return self.base.exists()

    def executable(self) -> str | None:
        """Where this agent's program is, or None if it cannot be found.

        PATH first, then the places an agent's own installer puts it. Returning None is an ordinary
        answer: it means this machine can show the person what to paste, not that anything is wrong.
        """
        for name in self.exe_names:
            found = shutil.which(name)
            if found:
                return found
        for rel in self.exe_rel:
            candidate = self.base / rel
            if candidate.is_file():
                return str(candidate)
        return None

    def run_modes(self) -> list[str]:
        """Which ways this agent can be started, best first — "acp", "oneshot", or neither."""
        if not self.executable():
            return []
        return [m for m, args in (("acp", self.acp_args), ("oneshot", self.oneshot_args)) if args]

    def resolve_install_path(self, dest: str | Path) -> Path:
        """Re-root a catalog path written against a *presumed* agent directory onto the real one.

        A catalog component carries a per-agent destination such as `~/.hermes/skills/ldap-notes`,
        written by whoever published it against the layout they had. On a machine where the agent
        lives elsewhere that path is not a preference, it is a stale guess — and honouring it puts
        the component in a folder the agent never reads, which is the exact failure discovery exists
        to prevent.

        So a destination that merely restates one of the layouts we already know about is rewritten
        onto the resolved base; anything else is honoured literally, because a path that matches no
        known layout was chosen deliberately and is not ours to second-guess.
        """
        # `~` is expanded against *this adapter's* home, not `os.path.expanduser`. The two differ,
        # and the difference is not academic: on Windows `expanduser()` reads `USERPROFILE` and
        # ignores a patched `Path.home()` entirely, so a suite that had carefully isolated itself in
        # a temporary directory still wrote a fixture component into the real user's home.
        path = Path(dest)
        if path.parts and path.parts[0] in ("~", "~/"):
            path = self.home.joinpath(*path.parts[1:])
        for rel in self.bases:
            candidate = self.home / rel
            try:
                inside = path.relative_to(candidate)
            except ValueError:
                continue
            return self.base / inside
        return path

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
        """Write the agent's MCP configuration back, keeping one copy of what was there before.

        This is somebody else's file, often long and maintained by hand, and we rewrite it through a
        parse/dump round trip to add a single entry — which preserves the data and loses comments and
        formatting. That is a poor trade to make silently on a file we do not own, so the version we
        found is kept beside it. Only the first write of a session creates the copy: later writes must
        not overwrite the pristine original with one we already touched.
        """
        self.mcp_config.parent.mkdir(parents=True, exist_ok=True)
        if self.mcp_config.exists():
            backup = self.mcp_config.with_suffix(self.mcp_config.suffix + ".autoskill-bak")
            if not backup.exists():
                backup.write_bytes(self.mcp_config.read_bytes())
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
