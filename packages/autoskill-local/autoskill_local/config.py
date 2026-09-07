"""Local configuration in ~/.autoskill/config.toml (server, api key, device, trials)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit

HOME = Path(os.environ.get("AUTOSKILL_HOME", Path.home() / ".autoskill"))


def config_path() -> Path:
    return HOME / "config.toml"


def _without_nulls(value):
    """Drop every `None` from a tree on its way into TOML, which has no way to write one.

    What we keep for a trial or an install is whatever the target adapter reported, and those records
    carry honest absences: an MCP server registered by URL has no `command`, one launched by command
    has no `url`. Handing that straight to tomlkit turned an ordinary missing field into
    `ConvertError: Unable to convert an object of <class 'NoneType'>` — raised *after* the skill had
    been installed and the server told about it, so the work was done, the traceback still filled the
    terminal, and nothing was left on disk to say the trial existed. Omission is the TOML spelling of
    absence, and reading it back gives the same `None` from `.get()`.
    """
    if isinstance(value, dict):
        return {k: _without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_without_nulls(v) for v in value if v is not None]
    return value


@dataclass
class LocalConfig:
    server_url: str | None = None
    api_key: str | None = None
    device_id: str | None = None
    trials: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )  # trial_id -> {token, target, skill, version, manifest}
    installs: dict[str, dict[str, Any]] = field(default_factory=dict)  # "<target>:<skill>" -> manifest
    # interview_id -> {token, url, project}: sessions this machine is the executor for
    interviews: dict[str, dict[str, Any]] = field(default_factory=dict)
    # target id -> {home}: where an agent lives when it is somewhere discovery does not look
    targets: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls) -> LocalConfig:
        path = config_path()
        if not path.exists():
            return cls(server_url=os.environ.get("AUTOSKILL_URL"), api_key=os.environ.get("AUTOSKILL_API_KEY"))
        data = tomlkit.parse(path.read_text()).unwrap()
        return cls(
            server_url=os.environ.get("AUTOSKILL_URL") or data.get("server_url"),
            api_key=os.environ.get("AUTOSKILL_API_KEY") or data.get("api_key"),
            device_id=data.get("device_id"),
            trials=dict(data.get("trials", {})),
            installs=dict(data.get("installs", {})),
            interviews=dict(data.get("interviews", {})),
            targets=dict(data.get("targets", {})),
        )

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = tomlkit.document()
        for key in ("server_url", "api_key", "device_id"):
            value = getattr(self, key)
            if value:
                doc[key] = value
        doc["trials"] = _without_nulls(self.trials)
        doc["installs"] = _without_nulls(self.installs)
        # declared as a field but never persisted until now: an interview this machine was the
        # executor for was forgotten the moment the process ended
        if self.interviews:
            doc["interviews"] = _without_nulls(self.interviews)
        if self.targets:
            doc["targets"] = _without_nulls(self.targets)
        path.write_text(tomlkit.dumps(doc))
        try:
            path.chmod(0o600)
        except OSError:
            pass
