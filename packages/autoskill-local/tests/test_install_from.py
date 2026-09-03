"""`autoskill install --from <install.json>`: download every artifact of a bundle, verify checksums, install
components and MCP servers, register them on the agent, and remove everything cleanly."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from autoskill_local import cli, client, config
from autoskill_local.config import LocalConfig
from autoskill_local.targets import get_target

BASE = "http://server/dl/tok"


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


SKILL_ZIP = _zip(
    {
        "invoice-check/SKILL.md": "---\nname: invoice-check\ndescription: d\n---\nbody\n",
        "invoice-check/autoskill.json": json.dumps({"skill": {"version": "0.1.0", "build": 3}}),
    }
)
TOOLS_ZIP = _zip({"pyproject.toml": '[project]\nname = "invoice-check-tools"\n', "invoice_check_tools/__init__.py": ""})
NOTES_ZIP = _zip({"ldap-notes/SKILL.md": "---\nname: ldap-notes\ndescription: d\n---\nb\n"})
FILES = {"/dl/tok/skill.zip": SKILL_ZIP, "/dl/tok/mcp/invoice-check-tools.zip": TOOLS_ZIP, "/dl/tok/components/ldap-notes/ldap-notes.zip": NOTES_ZIP}


def manifest(bad_sha: bool = False) -> dict:
    return {
        "format": "autoskill-install/1",
        "kind": "trial",
        "server_url": "http://server",
        "manifest_url": f"{BASE}/install.json",
        "default_target": "hermes",
        "skill": {
            "name": "invoice-check",
            "version": "0.1.0",
            "version_id": "v1",
            "build": 3,
            "download": {"url": f"{BASE}/skill.zip", "filename": "invoice-check-0.1.0.zip"},
        },
        "mcp_servers": [
            {"name": "autoskill-companion", "kind": "companion", "registration": {"command": "autoskill-companion"}},
            {
                "name": "invoice-check-tools",
                "kind": "generated",
                "download": {
                    "url": f"{BASE}/mcp/invoice-check-tools.zip",
                    "filename": "invoice-check-tools.zip",
                    "sha256": "0" * 64 if bad_sha else hashlib.sha256(TOOLS_ZIP).hexdigest(),
                },
                "install": {"method": "pipx_archive", "command": "pipx install ..."},
                "registration": {
                    "command": "invoice-check-tools",
                    "args": [],
                    "env_requirements": [{"name": "SMTP_HOST", "description": "smtp", "secret": False}],
                },
            },
            {
                "name": "email-mcp",
                "kind": "library",
                "install": {"method": "manual", "command": ""},
                "registration": {"url": "http://localhost:4010/mcp", "env_requirements": []},
            },
        ],
        "components": [
            {
                "slug": "ldap-notes",
                "kind": "skill",
                "download": {
                    "url": f"{BASE}/components/ldap-notes/ldap-notes.zip",
                    "filename": "ldap-notes.zip",
                    "sha256": hashlib.sha256(NOTES_ZIP).hexdigest(),
                },
                "install": {"method": "copy"},
                "install_paths": {"hermes": "~/.hermes/skills/ldap-notes"},
            }
        ],
        "trial": {"session_id": "t1", "target_agent": "hermes"},
    }


@pytest.fixture
def home(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))  # expanduser() of catalog install_paths
    monkeypatch.setattr(config, "HOME", home / ".autoskill")
    monkeypatch.setattr(cli, "HOME", home / ".autoskill")
    monkeypatch.setattr(client, "TRANSPORT", httpx.MockTransport(_handler))
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)  # no pipx, no companion on PATH
    calls: list[list[str]] = []
    monkeypatch.setattr(cli, "_run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    return home, calls


def _handler(request: httpx.Request) -> httpx.Response:
    data = FILES.get(request.url.path)
    if data is None:
        return httpx.Response(404, json={"error": {"code": "not_found"}})
    return httpx.Response(200, content=data, headers={"content-type": "application/zip"})


def test_install_from_manifest_and_clean_removal(home):
    home_dir, calls = home
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    folder, meta, record = cli._install_from_manifest(cfg, manifest(), "hermes", "trial-token")
    assert folder == "invoice-check" and meta["skill"]["build"] == 3
    t = get_target("hermes")
    assert (t.skill_dir / "invoice-check" / "SKILL.md").exists()
    assert (t.skill_dir / "ldap-notes" / "SKILL.md").exists()
    servers = t.registered_mcps()
    assert set(servers) == {"autoskill-companion", "invoice-check-tools", "email-mcp"}
    assert servers["autoskill-companion"]["env"]["AUTOSKILL_SESSION_TOKEN"] == "trial-token"
    venv_cmd = servers["invoice-check-tools"]["command"]
    assert venv_cmd.endswith("/venvs/invoice-check-tools/bin/invoice-check-tools")
    assert servers["invoice-check-tools"]["env"] == {"SMTP_HOST": "smtp.example"}
    assert servers["email-mcp"]["url"] == "http://localhost:4010/mcp"
    # the generated server was installed from the verified archive into a private venv
    assert [c[1:3] for c in calls] == [["-m", "venv"], ["-m", "pip"]]
    assert calls[1][-1].endswith("invoice-check-tools.zip")
    assert record["python_packages"][0]["method"] == "venv" and record["components"][0]["slug"] == "ldap-notes"
    assert record["manifest_url"] == f"{BASE}/install.json" and record["build"] == 3
    assert len(record["mcp"]) == 3

    cli._remove_bundle_parts(t, record)
    t.remove_skill("invoice-check", record)
    assert not (t.skill_dir / "invoice-check").exists() and not (t.skill_dir / "ldap-notes").exists()
    assert set(t.registered_mcps()) == {"autoskill-companion"}


def test_checksum_mismatch_refuses_to_install(home):
    cfg = LocalConfig(server_url="http://server")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        cli._install_from_manifest(cfg, manifest(bad_sha=True), "hermes", None)
    assert not (get_target("hermes").skill_dir / "invoice-check").exists()
