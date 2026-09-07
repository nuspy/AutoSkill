"""`autoskill install --from <install.json>`: download every artifact of a bundle, verify checksums, install
components and MCP servers, register them on the agent, and remove everything cleanly."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import httpx
import pytest

from autoskill_local import cli, client, config
from autoskill_local.config import LocalConfig
from autoskill_local.targets import get_target

# A venv puts its executables in `bin` on POSIX and `Scripts` on Windows. Asserting the POSIX
# spelling made these tests fail on Windows for a reason that has nothing to do with what they
# check — and a suite that is red for a known-irrelevant reason stops being read at all.
BIN = "Scripts" if os.name == "nt" else "bin"


def _venv_exe(home_dir: Path, name: str) -> Path:
    return home_dir / ".autoskill" / "venvs" / name / BIN / name


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
FILES = {
    "/dl/tok/skill.zip": SKILL_ZIP,
    "/dl/tok/mcp/invoice-check-tools.zip": TOOLS_ZIP,
    "/dl/tok/components/ldap-notes/ldap-notes.zip": NOTES_ZIP,
}


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
    assert Path(venv_cmd) == _venv_exe(home_dir, "invoice-check-tools")
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
    with pytest.raises(RuntimeError, match="checksum mismatch") as caught:
        cli._install_from_manifest(cfg, manifest(bad_sha=True), "hermes", None)
    # named, so a caller that is not a terminal can tell this from any other failure
    assert isinstance(caught.value, cli.LocalError) and caught.value.code == "checksum_mismatch"
    assert not (get_target("hermes").skill_dir / "invoice-check").exists()


def test_npm_git_and_binary_components(home, monkeypatch):
    home_dir, calls = home
    binary = b"#!/bin/sh\necho hi\n"
    FILES["/dl/tok/components/ldap-tool/ldap-tool"] = binary
    m = manifest()
    m["components"] = [
        {
            "slug": "ldap-tool",
            "kind": "plugin",
            "download": {
                "url": f"{BASE}/components/ldap-tool/ldap-tool",
                "filename": "ldap-tool",
                "sha256": hashlib.sha256(binary).hexdigest(),
            },
            "install": {"method": "binary"},
        },
    ]
    m["mcp_servers"] = [
        {"name": "autoskill-companion", "kind": "companion", "registration": {"command": "autoskill-companion"}},
        {
            "name": "calendar-mcp",
            "kind": "library",
            "install": {"method": "npm", "spec": "@acme/calendar-mcp", "command": "npm install -g @acme/calendar-mcp"},
            "registration": {"command": "calendar-mcp", "args": ["--stdio"], "env_requirements": []},
        },
        {
            "name": "crm-mcp",
            "kind": "library",
            "install": {
                "method": "git",
                "spec": "https://git.example/crm-mcp.git",
                "command": "pipx install git+https://git.example/crm-mcp.git@v2",
            },
            "registration": {"command": "crm-mcp", "env_requirements": []},
        },
    ]
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/npm" if name == "npm" else None)
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    _folder, _meta, record = cli._install_from_manifest(cfg, m, "hermes", None)
    t = get_target("hermes")
    servers = t.registered_mcps()
    assert servers["calendar-mcp"]["command"] == "calendar-mcp" and servers["calendar-mcp"]["args"] == ["--stdio"]
    assert Path(servers["crm-mcp"]["command"]) == _venv_exe(home_dir, "crm-mcp")
    assert ["npm", "install", "-g", "@acme/calendar-mcp"] in calls
    pip_call = next(c for c in calls if "pip" in c and "install" in c)
    assert pip_call[-1] == "git+https://git.example/crm-mcp.git@v2"
    tool = home_dir / ".autoskill" / "bin" / "ldap-tool"
    assert tool.read_bytes() == binary
    # Windows has no executable bit — `chmod` there cannot set one, and what makes a file runnable is
    # its extension. Asserting it would only test the operating system.
    assert os.name == "nt" or tool.stat().st_mode & 0o111
    methods = sorted(p["method"] for p in record["python_packages"])
    assert methods == ["binary", "npm", "venv"]
    cli._remove_bundle_parts(t, record)
    assert not tool.exists() and set(t.registered_mcps()) == {"autoskill-companion"}
    # Removal spawns its processes through the same `_run` as installation, so what it uninstalls is
    # visible here. It used to call `subprocess.run` directly, which this test asserted as if it were
    # intended: the practical effect was that removing a bundle really did try to launch npm in the
    # middle of a test run, and on a machine where the stubbed path does not exist it simply crashed.
    assert ["npm", "uninstall", "-g", "@acme/calendar-mcp"] in calls


# --- keeping the companion current -------------------------------------------------------------


def test_the_companion_is_upgraded_when_the_server_advertises_a_newer_one(home, monkeypatch):
    """It used to be installed only when missing, so a machine kept its first copy for ever.

    The manifest has always carried the companion's version; nothing compared it. So a server could
    ship a companion with new tools or corrected instructions and every install here went on
    registering the old one — silently, since registration succeeds either way.
    """
    _home_dir, _calls = home
    installed: list[str] = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/autoskill-companion" if name == "autoskill-companion" else None)
    monkeypatch.setattr(cli, "_install_python_package", lambda name, spec: (installed.append(spec) or ("cmd", {"method": "venv", "spec": spec})))
    monkeypatch.setattr(cli, "__version__", "0.2.3")

    m = manifest()
    m["mcp_servers"] = [
        {
            "name": "autoskill-companion",
            "kind": "companion",
            "version": "0.2.5",
            "download": {"url": f"{BASE}/companion.whl", "filename": "autoskill_local-0.2.5-py3-none-any.whl"},
            "registration": {"command": "autoskill-companion"},
        }
    ]
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cli._install_from_manifest(cfg, m, "hermes", None)
    assert installed == [f"{BASE}/companion.whl"], "a newer companion must be fetched even when one is present"


def test_a_companion_already_current_is_left_alone(home, monkeypatch):
    _home_dir, _calls = home
    installed: list[str] = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/autoskill-companion" if name == "autoskill-companion" else None)
    monkeypatch.setattr(cli, "_install_python_package", lambda name, spec: (installed.append(spec) or ("cmd", {})))
    monkeypatch.setattr(cli, "__version__", "0.2.5")

    m = manifest()
    m["mcp_servers"] = [
        {
            "name": "autoskill-companion",
            "kind": "companion",
            "version": "0.2.5",
            "download": {"url": f"{BASE}/companion.whl", "filename": "x.whl"},
            "registration": {"command": "autoskill-companion"},
        }
    ]
    cli._install_from_manifest(LocalConfig(server_url="http://server"), m, "hermes", None)
    assert installed == [], "reinstalling the same version on every install would be pure noise"


def test_version_comparison_is_numeric():
    assert cli._is_newer("0.2.10", "0.2.9") is True, "0.2.10 is newer than 0.2.9, not older"
    assert cli._is_newer("0.2.3", "0.2.3") is False
    assert cli._is_newer("0.2.3", "0.2.5") is False
    assert cli._is_newer(None, "0.2.3") is False
    # an unparseable build must not loop: refusing to upgrade is the recoverable answer
    assert cli._is_newer("0.0.0+dev", "0.2.3") is False


def test_a_locked_companion_explains_itself_and_leaves_the_install_standing(home, monkeypatch, capsys):
    """On Windows the upgrade fails whenever the agent is running, which is nearly always.

    The companion the agent started holds `python.exe` inside the virtualenv pipx must replace, and
    the install dies with `os error 32`. The raw error names two paths and a process id and leaves
    the person to deduce that the process is their own agent.
    """
    _home_dir, _calls = home
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/autoskill-companion" if name == "autoskill-companion" else None)
    monkeypatch.setattr(cli, "__version__", "0.2.3")

    def boom(name, spec):
        raise OSError("failed to copy file ... python.exe: The process cannot access the file because it is being used by another process. (os error 32)")

    monkeypatch.setattr(cli, "_install_python_package", boom)
    m = manifest()
    m["mcp_servers"] = [
        {
            "name": "autoskill-companion",
            "kind": "companion",
            "version": "0.2.6",
            "download": {"url": f"{BASE}/companion.whl", "filename": "x.whl"},
            "registration": {"command": "autoskill-companion"},
        }
    ]

    # the rest of the install still completes: a companion that could not be replaced still works
    _folder, _meta, record = cli._install_from_manifest(LocalConfig(server_url="http://server"), m, "hermes", None)
    assert record["mcp"], "the companion is still registered with the copy already installed"

    out = capsys.readouterr().out
    assert "holding its files open" in out, "the cause must be named, not just reported"
    assert "pipx install --force" in out and f"{BASE}/companion.whl" in out, "and the cure given verbatim"


# --- graduating from a trial ---------------------------------------------------------------------


TRIAL_MD = """---
name: invoice-check
metadata:
  version: 0.1.0
  autoskill_trial: t1
---
# Check the invoices

> ## ⚠ This copy is a trial — walk it, do not just run it
>
> **If the `autoskill-companion` tools are not available to you, stop and say so.**

## Steps
do the thing
"""
FINAL_ZIP = _zip({"invoice-check/SKILL.md": "---\nname: invoice-check\n---\n# Check the invoices\n\n## Steps\ndo the thing\n"})


def test_accepting_replaces_the_trial_copy_with_the_final_package(home, monkeypatch):
    """A trial copy tells the agent to stop when the companion is missing; a kept skill must not.

    Promotion used to delete one frontmatter line and leave the rest, so an accepted skill kept the
    banner that makes it refuse to run outside a trial — depending for ever on the machinery it was
    supposed to graduate from.
    """
    _home_dir, _calls = home
    t = get_target("hermes")
    skill_dir = t.skill_dir / "invoice-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(TRIAL_MD)
    backup = t.skill_dir / ".invoice-check.autoskill-backup"
    backup.mkdir()
    (backup / "SKILL.md").write_text("what was here before the trial")

    monkeypatch.setattr(cli, "_client", lambda cfg=None, **kw: type("C", (), {"get": staticmethod(lambda path: FINAL_ZIP)})())
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cfg.trials["t1"] = {
        "token": "tok", "target": "hermes", "skill": "invoice-check", "version": "0.1.0",
        "manifest": {"skill_dir": str(skill_dir), "version_id": "v1", "backup_dir": str(backup)},
    }

    cli._finish_trial(cfg, "t1", keep=True)

    text = (skill_dir / "SKILL.md").read_text()
    assert "This copy is a trial" not in text, "the trial banner must not survive acceptance"
    assert "autoskill_trial" not in text
    assert "do the thing" in text, "and the skill itself is still there"
    # what the machine looked like before the trial is not this function's business to destroy
    assert (backup / "SKILL.md").read_text() == "what was here before the trial"
    assert "hermes:invoice-check" in cfg.installs


def test_when_the_final_package_cannot_be_fetched_the_trial_markings_still_go(home, monkeypatch):
    _home_dir, _calls = home
    t = get_target("hermes")
    skill_dir = t.skill_dir / "invoice-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(TRIAL_MD)

    def offline(cfg=None, **kw):
        raise OSError("no route to host")

    monkeypatch.setattr(cli, "_client", offline)
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cfg.trials["t1"] = {
        "token": "tok", "target": "hermes", "skill": "invoice-check", "version": "0.1.0",
        "manifest": {"skill_dir": str(skill_dir), "version_id": "v1"},
    }
    cli._finish_trial(cfg, "t1", keep=True)

    text = (skill_dir / "SKILL.md").read_text()
    assert "This copy is a trial" not in text and "autoskill_trial" not in text
    assert "# Check the invoices" in text and "do the thing" in text


def test_accepting_a_trial_already_decided_in_the_browser_still_settles_the_copy(home, monkeypatch, capsys):
    """The outcome is normally chosen in the page, which then tells the person to run this command.

    Posting the outcome a second time is refused with `409 trial_not_open` — correctly, a closed trial
    is not decided twice. Treating that as failure meant the command died with a traceback having done
    none of the local work it exists for, and the copy on the machine stayed a trial copy for ever.
    """
    _home_dir, _calls = home
    t = get_target("hermes")
    skill_dir = t.skill_dir / "invoice-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(TRIAL_MD)

    class Refusing:
        @staticmethod
        def post(path, body=None, **kw):
            raise cli.ServerError(409, {"error": {"code": "trial_not_open", "message": "trial_not_open"}})

        @staticmethod
        def get(path):
            if path.endswith("/package.zip"):
                return FINAL_ZIP
            return {"trial": {"outcome": "accepted", "keep_installed": True}}

    monkeypatch.setattr(cli, "_client", lambda cfg=None, **kw: Refusing())
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cfg.trials["t1"] = {
        "token": "tok", "target": "hermes", "skill": "invoice-check", "version": "0.1.0",
        "manifest": {"skill_dir": str(skill_dir), "version_id": "v1"},
    }
    monkeypatch.setattr(cli, "_cfg", lambda: cfg)

    cli.trial_accept("t1", keep=True)

    assert "This copy is a trial" not in (skill_dir / "SKILL.md").read_text()
    assert "hermes:invoice-check" in cfg.installs
    assert "Already decided" in capsys.readouterr().out


def test_the_browsers_decision_wins_over_the_flag_typed_here(home, monkeypatch):
    """`--keep` must not resurrect a copy the person already chose to remove in the page."""
    _home_dir, _calls = home
    t = get_target("hermes")
    skill_dir = t.skill_dir / "invoice-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(TRIAL_MD)

    class Refusing:
        @staticmethod
        def post(path, body=None, **kw):
            raise cli.ServerError(409, {"error": {"code": "trial_not_open", "message": "trial_not_open"}})

        @staticmethod
        def get(path):
            return {"trial": {"outcome": "removed", "keep_installed": False}}

    monkeypatch.setattr(cli, "_client", lambda cfg=None, **kw: Refusing())
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cfg.trials["t1"] = {
        "token": "tok", "target": "hermes", "skill": "invoice-check", "version": "0.1.0",
        "manifest": {"skill_dir": str(skill_dir)},
    }
    monkeypatch.setattr(cli, "_cfg", lambda: cfg)

    cli.trial_accept("t1", keep=True)

    assert not skill_dir.exists(), "the page said remove, so it is removed"
    assert "hermes:invoice-check" not in cfg.installs


def test_a_server_refusal_is_a_sentence_not_a_traceback(monkeypatch, capsys):
    """A 409 from the server is an answer. Forty frames of httpx and typer buried the one useful line."""
    import typer

    def boom():
        raise cli.ServerError(409, {"error": {"code": "trial_not_open", "message": "This trial is closed."}})

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(typer.Exit) as exit_info:
        cli.main()
    assert exit_info.value.exit_code == 1
    err = capsys.readouterr().err
    assert "trial_not_open" in err and "This trial is closed." in err
    assert "Traceback" not in err


def test_a_trial_can_be_settled_with_its_token_on_a_machine_that_never_installed_it(home, monkeypatch, capsys):
    """The printed uninstall line carries the token, so it must run where it is pasted.

    Settling used to need this machine to still hold the trial's record — the normal case and not the
    only one: a config restored elsewhere, a second machine, someone following the command from the
    page on a laptop that never ran the install. The token is what proves the right to settle it.
    """
    _home_dir, _calls = home
    posted: list[tuple] = []

    class Server:
        @staticmethod
        def post(path, body=None, **kw):
            posted.append((path, body))
            return {"ok": True}

    monkeypatch.setattr(cli, "_client", lambda cfg=None, **kw: Server())
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")  # no trials recorded here
    monkeypatch.setattr(cli, "_cfg", lambda: cfg)

    cli.trial_remove("t-elsewhere", outcome="removed", token="the-token")

    assert posted and posted[0][0] == "/trials/t-elsewhere/outcome"
    out = capsys.readouterr().out
    assert "No local record" in out
    assert "no local copy was touched" in out.lower(), "it must not claim to have deleted anything"


def test_without_a_record_and_without_a_token_it_says_what_is_missing(home, monkeypatch):
    import typer

    _home_dir, _calls = home
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    monkeypatch.setattr(cli, "_cfg", lambda: cfg)
    with pytest.raises(typer.Exit):
        cli.trial_remove("t-unknown", outcome="removed", token=None)


# --- the application must learn that a skill was removed ----------------------------------------


class _Recorder:
    """A stand-in server that remembers what it was asked, and can be told to fail."""

    def __init__(self, installations=None, boom=False):
        self.calls: list[tuple] = []
        self.installations = installations or []
        self.boom = boom

    def post(self, path, body=None, **kw):
        self.calls.append(("POST", path, body))
        return {"id": "inst-1"}

    def get(self, path, **kw):
        self.calls.append(("GET", path, None))
        return self.installations

    def request(self, method, path, **kw):
        if self.boom:
            raise OSError("no route to host")
        self.calls.append((method, path, None))
        return {"ok": True}


def _installed(_home_dir, monkeypatch, server, record_extra=None):
    t = get_target("hermes")
    skill_dir = t.skill_dir / "invoice-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: invoice-check\n---\nbody\n")
    monkeypatch.setattr(cli, "_client", lambda cfg=None, **kw: server)
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cfg.installs["hermes:invoice-check"] = {"version_id": "v1", **(record_extra or {})}
    monkeypatch.setattr(cli, "_cfg", lambda: cfg)
    return cfg, skill_dir


def test_removing_a_skill_tells_the_application_it_is_gone(home, monkeypatch):
    """`autoskill remove` deleted the files and said nothing, so the app kept listing the skill."""
    _home_dir, _calls = home
    server = _Recorder()
    cfg, skill_dir = _installed(_home_dir, monkeypatch, server, {"installation_id": "inst-7"})

    cli.remove("invoice-check", target="hermes")

    assert not skill_dir.exists()
    assert ("DELETE", "/me/installations/inst-7", None) in server.calls
    assert "hermes:invoice-check" not in cfg.installs


def test_an_install_keeps_the_id_the_server_answered_with(home, monkeypatch):
    """Without it there is nothing for a later removal to address."""
    _home_dir, _calls = home
    server = _Recorder()
    monkeypatch.setattr(cli, "_client", lambda cfg=None, **kw: server)
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    got = cli._register_installation(cfg, "v1", "hermes", "cli")
    assert got == "inst-1"


def test_an_older_record_without_the_id_is_matched_by_version_and_agent(home, monkeypatch):
    _home_dir, _calls = home
    server = _Recorder(installations=[
        {"id": "other", "skill_version_id": "v9", "target_agent": "hermes"},
        {"id": "inst-match", "skill_version_id": "v1", "target_agent": "hermes"},
    ])
    _cfg, skill_dir = _installed(_home_dir, monkeypatch, server)  # no installation_id in the record

    cli.remove("invoice-check", target="hermes")

    assert not skill_dir.exists()
    assert ("DELETE", "/me/installations/inst-match", None) in server.calls


def test_an_unreachable_server_never_stops_a_removal(home, monkeypatch, capsys):
    """The files are on this machine and the person asked for them to go."""
    _home_dir, _calls = home
    server = _Recorder(boom=True)
    cfg, skill_dir = _installed(_home_dir, monkeypatch, server, {"installation_id": "inst-7"})

    cli.remove("invoice-check", target="hermes")

    assert not skill_dir.exists(), "a bookkeeping failure must not leave the skill installed"
    assert "hermes:invoice-check" not in cfg.installs
    assert "could not tell AutoSkill" in capsys.readouterr().out


# --- installing without a terminal ----------------------------------------------------------------


def test_the_values_an_install_will_ask_for_are_knowable_before_it_starts():
    """A terminal can be prompted halfway through; a web page has to ask while it still has the person.

    Reading them off the manifest is the difference between a form filled once and an installation
    that stops in the middle with nowhere to put the question.
    """
    names = cli.required_env(manifest())
    assert names == ["SMTP_HOST"], "declared by the generated server, and nothing else"
    # the companion asks for nothing of the person, and a server reached by URL has nothing to launch
    assert "AUTOSKILL_API_KEY" not in names


def test_an_install_can_be_given_its_env_instead_of_prompting(home, monkeypatch):
    _home_dir, _calls = home

    def explode(_names):
        raise AssertionError("a caller with no terminal must never reach the prompt")

    monkeypatch.setattr(cli, "_ask_env", explode)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    said: list[str] = []

    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cli._install_from_manifest(
        cfg,
        manifest(),
        "hermes",
        None,
        env_provider=cli.env_from({"SMTP_HOST": "smtp.given"}),
        progress=said.append,
    )

    servers = get_target("hermes").registered_mcps()
    assert servers["invoice-check-tools"]["env"] == {"SMTP_HOST": "smtp.given"}
    # progress went to the caller rather than to stdout, which is where a host has to relay it from
    assert any("ldap-notes" in line for line in said)


def test_a_value_that_was_not_supplied_is_simply_absent(home, monkeypatch):
    """An optional value left blank must not stop an install, exactly as an unanswered prompt does not."""
    _home_dir, _calls = home
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")

    cli._install_from_manifest(cfg, manifest(), "hermes", None, env_provider=cli.env_from({}))

    assert "env" not in get_target("hermes").registered_mcps()["invoice-check-tools"]


def test_the_machine_state_is_a_value_and_doctor_only_prints_it(home, monkeypatch, capsys):
    """`doctor` had the answer and could only print it; the extension needs the same answer as data."""
    _home_dir, _calls = home
    cfg = LocalConfig(server_url="http://server", api_key="ask_x", device_id="dev-1")
    cfg.trials["t1"] = {"token": "tok", "target": "hermes", "skill": "invoice-check", "version": "0.1.0"}
    monkeypatch.setattr(cli, "_cfg", lambda: cfg)

    state = cli.machine_state()

    assert state["server_url"] == "http://server" and state["logged_in"] is True
    assert state["device_id"] == "dev-1" and state["cli_version"]
    # every known agent, not only the ones detection found — that is the whole point
    assert {a["id"] for a in state["agents"]} == set(cli.TARGETS)
    hermes = next(a for a in state["agents"] if a["id"] == "hermes")
    assert set(hermes) == {"id", "display_name", "detected", "base", "base_source", "skill_dir", "mcp_config", "companion"}
    assert hermes["base_source"] in ("configured", "found", "assumed") or hermes["base_source"].startswith("$")
    assert state["trials"] == [{"id": "t1", "skill": "invoice-check", "version": "0.1.0", "target": "hermes"}]

    cli.doctor()
    printed = capsys.readouterr().out
    assert "agents detected:" in printed and hermes["display_name"] in printed
    assert "invoice-check@0.1.0" in printed


def test_nothing_in_a_settlement_escapes_to_stdout_when_a_channel_is_given(home, monkeypatch, capsys):
    """A host relays what it is told. A line printed instead of returned is a line it never sees.

    The pieces that report — the component that cannot be installed automatically, the companion that
    could not be replaced, the bookkeeping call that failed — were each printing directly, so the
    useful half of an install went to a terminal that, for this caller, does not exist.
    """
    _home_dir, _calls = home
    t = get_target("hermes")
    skill_dir = t.skill_dir / "invoice-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: invoice-check\n---\nbody\n")

    def offline(cfg=None, **kw):
        raise OSError("no route to host")

    monkeypatch.setattr(cli, "_client", offline)
    cfg = LocalConfig(server_url="http://server", api_key="ask_x")
    cfg.trials["t1"] = {
        "token": "tok", "target": "hermes", "skill": "invoice-check", "version": "0.1.0",
        "manifest": {"skill_dir": str(skill_dir), "version_id": "v1"},
    }
    said: list[str] = []

    cli._finish_trial(cfg, "t1", keep=True, say=said.append)

    assert capsys.readouterr().out == "", "with a channel given, nothing may reach stdout"
    # and the caller was told both what failed and what happened anyway
    assert any("could not fetch the final package" in line for line in said)
    assert any("kept as a permanent installation" in line for line in said)
