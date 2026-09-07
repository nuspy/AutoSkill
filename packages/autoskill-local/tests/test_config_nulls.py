"""Saving the local config must survive the records the adapters actually produce.

Seen on a real machine: `autoskill trial install` downloaded the skill, registered the MCP server,
reported the installation to the server — and then died on `cfg.save()` with

    ConvertError: Unable to convert an object of <class 'NoneType'> to a TOML item

TOML cannot write a null, and the install record legitimately contains them: an MCP server registered
by URL has no `command`, one launched by command has no `url`, so one of the two is always `None`.
The work was already done and reported; all the traceback achieved was to leave nothing on disk
saying the trial existed, so every later `autoskill trial` command could no longer see it.
"""

from __future__ import annotations

from pathlib import Path

import tomlkit

from autoskill_local import config
from autoskill_local.config import LocalConfig


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "HOME", tmp_path)


def test_a_record_with_missing_fields_still_saves(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cfg.trials["trial-1"] = {
        "token": "tok",
        "target": "hermes",
        "skill": "excel-lists",
        "version": "0.1.0",
        # exactly the shape a target adapter returns: one of command/url is always absent
        "manifest": {"mcp": [{"name": "email", "command": None, "url": "http://mcp", "args": []}]},
    }

    cfg.save()  # used to raise ConvertError

    saved = tomlkit.parse(config.config_path().read_text())
    entry = saved["trials"]["trial-1"]
    assert entry["skill"] == "excel-lists"
    assert "command" not in entry["manifest"]["mcp"][0], "a null must be omitted, not written"
    assert entry["manifest"]["mcp"][0]["url"] == "http://mcp"


def test_what_is_omitted_reads_back_as_none(tmp_path: Path, monkeypatch) -> None:
    """Omission is TOML's spelling of absence: the round trip must give back the same `None`."""
    _isolate(tmp_path, monkeypatch)
    cfg = LocalConfig()
    cfg.installs["hermes:excel-lists"] = {"version": "0.1.0", "url": None, "env": {"A": "1", "B": None}}
    cfg.save()

    back = LocalConfig.load()
    record = back.installs["hermes:excel-lists"]
    assert record.get("url") is None
    assert record["env"] == {"A": "1"}
    assert record["version"] == "0.1.0"


def test_a_null_nested_in_a_list_does_not_stop_the_save(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    cfg = LocalConfig()
    cfg.trials["t"] = {"manifest": {"files": ["SKILL.md", None, "refs.md"], "steps": [{"key": "a", "note": None}]}}
    cfg.save()

    saved = tomlkit.parse(config.config_path().read_text())
    assert saved["trials"]["t"]["manifest"]["files"] == ["SKILL.md", "refs.md"]
    assert "note" not in saved["trials"]["t"]["manifest"]["steps"][0]
