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


@dataclass
class LocalConfig:
    server_url: str | None = None
    api_key: str | None = None
    device_id: str | None = None
    trials: dict[str, dict[str, Any]] = field(default_factory=dict)  # trial_id -> {token, target, skill, version, manifest}
    installs: dict[str, dict[str, Any]] = field(default_factory=dict)  # "<target>:<skill>" -> manifest

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
        )

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = tomlkit.document()
        for key in ("server_url", "api_key", "device_id"):
            value = getattr(self, key)
            if value:
                doc[key] = value
        doc["trials"] = self.trials
        doc["installs"] = self.installs
        path.write_text(tomlkit.dumps(doc))
        try:
            path.chmod(0o600)
        except OSError:
            pass
