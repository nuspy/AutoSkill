"""`autoskill` command line: login, trial install/sync/accept/remove, install/remove/list, doctor."""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import typer

from autoskill_local import __version__
from autoskill_local.client import Client, ServerError, fetch_json, fetch_url
from autoskill_local.config import HOME, LocalConfig, config_path
from autoskill_local.targets import TARGETS, detect_targets, get_target, set_home_overrides
from autoskill_local.targets.base import McpRegistration

# --- what a second caller needs -----------------------------------------------------------------
#
# Everything below exists so these functions can be driven by something other than a terminal — the
# browser extension's native messaging host is the first such caller. Three things stood in the way:
# the install prompts on a TTY, it reports by printing, and it fails by raising `typer.Exit`. Each is
# now a parameter with the old behaviour as its default, so no existing command changes.

EnvProvider = Callable[[list[str]], dict[str, str]]
Progress = Callable[[str], None]


class LocalError(RuntimeError):
    """A failure with a name, so a caller that is not a terminal can act on it.

    `typer.Exit` says only "stop"; a host relaying to a web page has to say *what* went wrong, and a
    checksum mismatch is a different matter from an agent that is not installed.

    It stays a `RuntimeError` deliberately: existing handlers catch that (`_promote_to_permanent`
    among them), and giving a failure a name must not quietly stop it from being caught.
    """

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.details = details
        super().__init__(message)


# `pretty_exceptions_enable=False`: a refusal from the server is an answer, not a crash, and forty
# lines of frames spanning httpx and typer buried the one line that said what happened. `main` turns
# those into a sentence; a genuine bug still raises and still shows its traceback.
app = typer.Typer(
    help="AutoSkill on your machine: install and trial skills on your own agent.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
trial_app = typer.Typer(help="Temporary installations tested step by step with AutoSkill.")
app.add_typer(trial_app, name="trial")


def _cfg() -> LocalConfig:
    """Load the configuration and, in the same breath, tell the adapters where the agents live.

    Every command goes through here, which is the point: the alternative was to thread the person's
    `[targets.*] home` settings through a dozen call sites, where they would have been forgotten at
    precisely the one that mattered — and a forgotten override is silent, since installing to the
    wrong directory succeeds.
    """
    cfg = LocalConfig.load()
    set_home_overrides({tid: rec.get("home") for tid, rec in cfg.targets.items()})
    return cfg


def _client(cfg: LocalConfig | None = None, trial_token: str | None = None) -> Client:
    cfg = cfg or _cfg()
    if not cfg.server_url:
        raise typer.BadParameter("not logged in: run `autoskill login <server-url>` first")
    return Client(cfg.server_url, api_key=cfg.api_key, trial_token=trial_token)


def _refresh_device(cfg: LocalConfig) -> None:
    """Tell the server which agents this machine has, now rather than at login.

    `agent_targets` used to be sent once, during `autoskill login`, and never again. Install an agent
    the day after and the server still believed it was not there — which is not merely cosmetic: the
    dashboard offers those targets when starting a trial, so the record being months out of date is
    the difference between an accurate list and a guess. It cost a real diagnosis: a trial installed
    correctly under Hermes looked, from the server's side, like a trial sent to an agent that did not
    exist.

    Detection is a few directory checks, so this is cheap; failing to report is never worth
    interrupting the command the person actually asked for.
    """
    if not cfg.server_url or not cfg.api_key:
        return
    try:
        _client(cfg).post(
            "/devices/heartbeat",
            {"cli_version": __version__, "agent_targets": detect_targets(), "os": platform.system()},
        )
    except Exception:  # noqa: BLE001, S110 - bookkeeping must not break an install
        pass


def _fail(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    typer.echo(f"autoskill-local {__version__}")


@app.command()
def login(server_url: str, no_browser: bool = False) -> None:
    """Connect this machine to an AutoSkill server (device-code flow)."""
    cfg = _cfg()
    cfg.server_url = server_url.rstrip("/")
    client = Client(cfg.server_url)
    start = client.post(
        "/auth/device",
        {
            "device_name": socket.gethostname(),
            "device_os": f"{platform.system()} {platform.release()}",
            "agent_targets": detect_targets(),
        },
    )
    typer.echo(f"Open {start['verification_uri']}?code={start['user_code']} and enter the code: {start['user_code']}")
    if not no_browser:
        webbrowser.open(f"{start['verification_uri']}?code={start['user_code']}")
    deadline = time.time() + start["expires_in"]
    while time.time() < deadline:
        time.sleep(start.get("interval", 5))
        res = client.post("/auth/device/token", {"device_code": start["device_code"]})
        if res["status"] == "approved":
            cfg.api_key = res["api_key"]
            cfg.device_id = res.get("device_id")
            cfg.save()
            typer.secho("Connected. Configuration saved in " + str(HOME / "config.toml"), fg=typer.colors.GREEN)
            _client(cfg).post(
                "/devices/heartbeat",
                {"cli_version": __version__, "agent_targets": detect_targets(), "os": platform.system()},
            )
            return
        if res["status"] in ("denied", "expired"):
            _fail(f"login {res['status']}")
    _fail("login timed out")


skill_app = typer.Typer(help="Create a skill from here; the interview itself happens in the browser.")
app.add_typer(skill_app, name="skill")


@skill_app.command("new")
def skill_new(
    description: str = typer.Argument(..., help="What the recurring task is, in your own words"),
    project: str | None = typer.Option(None, "--project", help="Project slug (needed when you have several)"),
    title: str | None = typer.Option(None, "--title"),
    language: str = typer.Option("en", "--language"),
    no_browser: bool = False,
) -> None:
    """Open an AutoSkill interview and hand it to the browser.

    AutoSkill leads the interview and you answer there; this machine stays attached as the executor,
    so the interview can look at your folders and files instead of asking you to recall them.
    """
    cfg = _cfg()
    if not cfg.server_url or not cfg.api_key:
        _fail("run `autoskill login <server-url>` first")
    try:
        res = _client(cfg).post(
            "/interviews/agent",
            {"description": description, "project": project, "title": title, "language": language},
        )
    except ServerError as exc:
        if exc.code == "choose_project":
            details = (exc.body or {}).get("error", {}).get("details", {}) if isinstance(exc.body, dict) else {}
            options = ", ".join(p["slug"] for p in details.get("projects", []))
            _fail(f"several projects: repeat with --project <slug> ({options})")
        raise
    cfg.interviews[res["session_id"]] = {
        "token": res["session_token"], "url": res["url"], "project": res["project"]
    }
    cfg.save()
    typer.secho("Interview opened. Continue in the browser:", fg=typer.colors.GREEN)
    typer.echo(f"  {res['url']}")
    typer.echo("")
    typer.echo("Then tell your agent to assist it, pasting this line:")
    typer.echo(
        f"  Assist AutoSkill interview {res['session_id']}: call `assist_interview` with "
        f"session_key='{res['session_token']}', then loop `await_task` / `report_task` until done."
    )
    if not no_browser:
        webbrowser.open(res["url"])


@skill_app.command("assistant")
def skill_assistant(
    target: str | None = typer.Option(None, "--target", help="Agent id; all detected ones by default"),
) -> None:
    """Install the `autoskill` skill, which teaches your agent how to work with AutoSkill.

    Without it an agent has no idea what to do when you ask it to automate something, or when you
    paste a line asking it to assist an interview.
    """
    cfg = _cfg()
    if not cfg.server_url:
        _fail("run `autoskill login <server-url>` first")
    data = fetch_url(f"{cfg.server_url.rstrip('/')}/dl/skill/autoskill.zip")
    root = _single_root(_extract_zip(data))
    targets = [target] if target else detect_targets()
    if not targets:
        _fail("no agent detected on this machine; pass --target explicitly")
    for tid in targets:
        t = get_target(tid)
        dest = t.skill_dir / root.name
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root, dest)
        typer.secho(f"{tid}: installed {dest}", fg=typer.colors.GREEN)
    typer.echo("Restart your agent session so it picks the skill up.")


def machine_state(cfg: LocalConfig | None = None) -> dict[str, Any]:
    """What this machine looks like: the server it answers to, every known agent, the open trials.

    Every known agent is described, found or not, with the directory that was resolved and how it was
    decided — which is exactly the information that is useless when it arrives only for the agents
    detection already found. An agent installed somewhere unusual was simply absent from the list,
    indistinguishable from one that is not installed at all.

    A value rather than print output, because the browser extension needs the same answer `doctor`
    prints, and reading it back off a terminal is not an interface.
    """
    cfg = cfg or _cfg()
    agents = []
    for tid in TARGETS:
        t = get_target(tid)
        here = t.detect()
        # `registered_mcps` reads the agent's config file; there is nothing to read if it is absent.
        companion = None
        if here:
            try:
                companion = "registered" if "autoskill-companion" in t.registered_mcps() else "missing"
            except Exception as exc:  # noqa: BLE001 - a config we cannot parse is a finding, not a crash
                companion = f"unreadable ({exc.__class__.__name__})"
        agents.append(
            {
                "id": tid,
                "display_name": t.display_name,
                "detected": here,
                "base": str(t.base),
                "base_source": t.base_source,
                "skill_dir": str(t.skill_dir),
                "mcp_config": str(t.mcp_config),
                "companion": companion,
            }
        )
    return {
        "cli_version": __version__,
        "server_url": cfg.server_url,
        "logged_in": bool(cfg.api_key),
        "device_id": cfg.device_id,
        "config_path": str(config_path()),
        "agents": agents,
        "trials": [
            {"id": sid, "skill": v.get("skill"), "version": v.get("version"), "target": v.get("target")}
            for sid, v in cfg.trials.items()
        ],
        "installs": sorted(cfg.installs),
    }


@app.command()
def doctor() -> None:
    """Show detected agents, configuration and companion registration."""
    state = machine_state()
    typer.echo(
        f"server: {state['server_url'] or '-'}   logged in: {'yes' if state['logged_in'] else 'no'}   "
        f"device: {state['device_id'] or '-'}"
    )
    found = [a["id"] for a in state["agents"] if a["detected"]]
    typer.echo("agents detected: " + (", ".join(found) or "none"))
    typer.echo("where each agent is looked for:")
    for a in state["agents"]:
        typer.echo(f"  {'✓' if a['detected'] else ' '} {a['display_name']} [{a['id']}]")
        typer.echo(f"      dir: {a['base']}  ({a['base_source']})")
        typer.echo(f"      skills: {a['skill_dir']}   config: {a['mcp_config']}   companion: {a['companion'] or '-'}")
    typer.echo(
        f"an agent living elsewhere: add it to {config_path()} as\n"
        '  [targets.<agent>]\n  home = "<full path to the agent directory>"'
    )
    if state["trials"]:
        typer.echo(
            "open trials: " + ", ".join(f"{v['skill']}@{v['version']} ({v['target']})" for v in state["trials"])
        )


def _companion_registration(cfg: LocalConfig, trial_token: str | None = None) -> McpRegistration:
    env = {"AUTOSKILL_URL": cfg.server_url or "", "AUTOSKILL_API_KEY": cfg.api_key or ""}
    if trial_token:
        env["AUTOSKILL_SESSION_TOKEN"] = trial_token
    command = shutil.which("autoskill-companion") or "autoskill-companion"
    return McpRegistration(name="autoskill-companion", command=command, args=[], env=env)


@app.command("companion")
def companion(action: str = typer.Argument("register"), target: str = typer.Option(..., "--target")) -> None:
    """Register (or unregister) the companion MCP server in an agent's configuration."""
    cfg = _cfg()
    t = get_target(target)
    if action == "register":
        t.register_mcp(_companion_registration(cfg))
        typer.echo(f"autoskill-companion registered in {t.mcp_config}")
    else:
        t.unregister_mcp("autoskill-companion")
        typer.echo("autoskill-companion removed")


browser_app = typer.Typer(help="The browser extension that installs skills without a terminal.")
app.add_typer(browser_app, name="browser")


@browser_app.command("install")
def browser_install(
    extension_id: list[str] = typer.Option(  # noqa: B008 - typer declares options this way
        [], "--extension-id", help="ids permitted to drive this machine; the shipped one by default"
    ),
    browser: list[str] = typer.Option([], "--browser", help="chrome, chromium, opera, edge; all by default"),  # noqa: B008
) -> None:
    """Tell this machine's browsers about the AutoSkill native messaging host.

    The half of the bootstrap that can be automated. It writes under the current user and needs no
    administrator; what it cannot do is install the extension itself, because Chrome has not allowed
    an extension to be installed from a local file since version 33.
    """
    from autoskill_local import browserhost, nativehost

    ids = list(extension_id) or list(nativehost.EXTENSION_IDS)
    if not ids:
        _fail(
            "no extension id: pass --extension-id <id> (Chrome shows it on chrome://extensions with "
            "Developer mode on). Registering a host that nothing is allowed to call would do nothing."
        )
    written = browserhost.install(ids, browsers=list(browser) or None)
    if not written:
        _fail("no browser on this machine has a place to register the host")
    for where in written:
        typer.echo(f"registered in {where}")
    typer.secho(f"{browserhost.HOST_NAME} -> {browserhost.host_executable()}", fg=typer.colors.GREEN)
    typer.echo(f"allowed to call it: {', '.join(ids)}")


def _download_package(client: Client, path: str) -> tuple[Path, dict[str, Any], str]:
    data = client.get(path)
    tmp = Path(tempfile.mkdtemp(prefix="autoskill-pkg-"))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(tmp)
    roots = [p for p in tmp.iterdir() if p.is_dir()]
    if len(roots) != 1:
        raise RuntimeError("unexpected package layout")
    root = roots[0]
    meta = json.loads((root / "autoskill.json").read_text()) if (root / "autoskill.json").exists() else {}
    return root, meta, root.name


def _install(
    cfg: LocalConfig,
    target: str,
    root: Path,
    meta: dict[str, Any],
    skill_name: str,
    trial_token: str | None,
    env_values: dict[str, str],
) -> dict[str, Any]:
    t = get_target(target)
    manifest: dict[str, Any] = {
        "target": target,
        "skill": skill_name,
        "build": meta.get("build", 1),
        "version": meta.get("version"),
    }
    manifest.update(t.install_skill(root, skill_name))
    reg = _companion_registration(cfg, trial_token)
    reg.env.update(env_values)
    manifest["mcp"] = [t.register_mcp(reg)]
    return manifest


def _register_installation(
    cfg: LocalConfig, version_id: str, target: str, channel: str, say: Progress = typer.echo
) -> str | None:
    """Tell the server this machine installed the version, and keep the id it answers with.

    The id was thrown away, which left removal with nothing to address: `autoskill remove` deleted the
    files and said nothing to anybody, so the application went on listing a skill that was gone.
    Never fatal — reporting an install is bookkeeping, and must not break the install.
    """
    try:
        res = _client(cfg).post(
            "/me/installations",
            {
                "skill_version_id": version_id,
                "target_agent": target,
                "channel": channel,
                "state": "installed",
                "device_id": cfg.device_id,
            },
        )
        return res.get("id") if isinstance(res, dict) else None
    except Exception as exc:  # noqa: BLE001
        say(f"(could not register the installation with AutoSkill: {exc})")
        return None


def _report_removal(cfg: LocalConfig, manifest: dict[str, Any], target: str, say: Progress = typer.echo) -> None:
    """Tell the server the skill is no longer installed here.

    The id comes from the install record; installs made before it was kept have none, so the row is
    looked up by version and agent instead. Failing to report must never stop a removal: the files are
    on this machine and the person asked for them to go, whatever the server thinks.
    """
    if not cfg.server_url or not cfg.api_key:
        return
    installation_id = manifest.get("installation_id")
    version_id = manifest.get("version_id")
    try:
        client = _client(cfg)
        if not installation_id and version_id:
            rows = client.get("/me/installations")
            match = next(
                (
                    r
                    for r in (rows if isinstance(rows, list) else [])
                    if r.get("skill_version_id") == version_id and r.get("target_agent") == target
                ),
                None,
            )
            installation_id = match.get("id") if match else None
        if installation_id:
            client.request("DELETE", f"/me/installations/{installation_id}")
    except Exception as exc:  # noqa: BLE001
        say(f"(could not tell AutoSkill about the removal: {exc})")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch_artifact(ref: dict[str, Any]) -> bytes:
    """Download an artifact of the bundle and verify its checksum when the bundle gives one."""
    data = fetch_url(ref["url"])
    expected = ref.get("sha256")
    if expected and _sha256(data) != expected:
        raise LocalError(
            "checksum_mismatch",
            f"checksum mismatch for {ref['url']}: refusing to install",
            url=ref["url"],
        )
    return data


def _extract_zip(data: bytes) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="autoskill-dl-"))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(tmp)
    return tmp


def _single_root(tmp: Path) -> Path:
    entries = list(tmp.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return tmp


def _version_parts(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.+-]", v or "0"))


def _is_newer(advertised: str | None, installed: str) -> bool:
    """Whether the server's companion is newer than this one, comparing numerically where possible.

    A string comparison would call 0.2.10 older than 0.2.9. Anything unparseable — a dev build, a
    local suffix — is treated as not newer: refusing to upgrade is recoverable, upgrading in a loop
    because two versions never compare equal is not.
    """
    if not advertised or advertised == installed:
        return False
    try:
        return _version_parts(advertised) > _version_parts(installed)
    except TypeError:
        return False


def _companion_install_failed(
    exc: Exception, *, updating: bool, wanted: str | None, url: str, say: Progress = typer.echo
) -> None:
    """Explain a failed companion install, and name the cause when it is the usual one.

    On Windows an upgrade fails whenever the agent is running, which is nearly always: the companion
    it started holds `python.exe` inside the very virtualenv pipx has to replace, and the install dies
    with `os error 32`. The bare exception text mentions two paths and a process id and leaves the
    person to work out that their agent is the process — so the cure is spelled out instead. The
    install is left untouched when this happens: the previous companion keeps working.
    """
    text = f"{exc}\n{getattr(exc, 'stderr', '') or ''}{getattr(exc, 'stdout', '') or ''}"
    locked = "os error 32" in text or "used by another process" in text or "being used by another" in text
    what = "update" if updating else "install"
    if locked:
        say(
            f"Could not {what} autoskill-local to {wanted}: your agent is running the current companion "
            "and is holding its files open."
        )
        say("  Close the agent, run this, then start it again:")
        say(f"    pipx install --force {url}")
        say("  Everything else was installed; the companion you already have keeps working.")
        return
    say(f"(could not {what} autoskill-local automatically: {exc})")


def _run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True, **kw)


def _install_python_package(name: str, spec: str) -> tuple[str, dict[str, Any]]:
    """Make the console script `name` available: with pipx when present, else in a private venv.

    `spec` is anything pip accepts (a downloaded archive path, a URL, a package name)."""
    if shutil.which("pipx"):
        _run(["pipx", "install", "--force", spec])
        return shutil.which(name) or name, {"method": "pipx", "spec": spec, "package": name}
    venv = HOME / "venvs" / name
    venv.parent.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "venv", str(venv)])
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    _run([str(bin_dir / "python"), "-m", "pip", "install", "-q", spec])
    return str(bin_dir / name), {"method": "venv", "path": str(venv), "spec": spec, "package": name}


def _install_binary(name: str, ref: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Download a single executable into ~/.autoskill/bin (checksum verified) and make it runnable."""
    data = _fetch_artifact(ref)
    bin_dir = HOME / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / name
    target.write_bytes(data)
    target.chmod(0o755)
    return str(target), {"method": "binary", "path": str(target), "package": name}


def _install_component_package(
    name: str, install: dict[str, Any], download: dict[str, Any] | None, say: Progress = typer.echo
) -> tuple[str | None, dict[str, Any] | None]:
    """Install an MCP/plugin package by its declared method; returns (command, removal record) or (None, None)."""
    method = install.get("method")
    spec = install.get("spec")
    if download and method in ("pipx_archive", "pipx", "pip"):
        data = _fetch_artifact(download)
        archive = Path(tempfile.mkdtemp(prefix="autoskill-mcp-")) / download["filename"]
        archive.write_bytes(data)
        return _install_python_package(name, str(archive))
    if method in ("pipx", "pip") and spec:
        return _install_python_package(name, spec)
    if method == "git" and spec:
        ref = ""
        cmd = install.get("command", "")
        if "@" in cmd.split("git+", 1)[-1]:
            ref = "@" + cmd.split("git+", 1)[-1].split("@", 1)[1].split("#", 1)[0]
        return _install_python_package(name, f"git+{spec}{ref}")
    if method == "npm" and spec:
        if not shutil.which("npm"):
            say(f"{name}: npm is not installed; run `{install.get('command', 'npm install -g ' + spec)}` yourself")
            return None, None
        _run(["npm", "install", "-g", spec])
        return shutil.which(name) or name, {"method": "npm", "package": spec}
    if method == "binary" and download:
        return _install_binary(name, download)
    if install.get("command") and method not in ("copy", "none"):
        say(f"{name}: install it first with `{install['command']}` (not automated)")
    return None, None


def _install_from_manifest(
    cfg: LocalConfig,
    manifest: dict[str, Any],
    target: str,
    trial_token: str | None,
    *,
    env_provider: EnvProvider | None = None,
    progress: Progress | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Install everything an install.json bundle lists, in order: components, MCP servers, skill.

    Returns (skill folder name, skill metadata, install manifest for a clean removal)."""
    ask = env_provider or _ask_env
    say = progress or typer.echo
    t = get_target(target)
    skill = manifest["skill"]
    record: dict[str, Any] = {
        "target": target,
        "skill": skill["name"],
        "version": skill.get("version"),
        "version_id": skill.get("version_id"),
        "build": skill.get("build", 1),
        "manifest_url": manifest.get("manifest_url"),
        "components": [],
        "mcp": [],
        "python_packages": [],
    }
    # 1. shared components (catalog skills / plugins)
    for comp in manifest.get("components", []):
        method = (comp.get("install") or {}).get("method")
        download = comp.get("download")
        if download and method == "copy":
            root = _single_root(_extract_zip(_fetch_artifact(download)))
            dest = comp.get("install_paths", {}).get(target)
            info = t.install_skill(root, comp["slug"])
            target_dir = t.resolve_install_path(dest) if dest else None
            if target_dir and target_dir != Path(info["skill_dir"]):
                # the catalog asked for a specific folder on this agent
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(info["skill_dir"], target_dir)
                info["skill_dir"] = str(target_dir)
            record["components"].append({"slug": comp["slug"], **info})
            say(f"component {comp['slug']} installed in {info['skill_dir']}")
        else:
            cmd, rec = _install_component_package(comp["slug"], comp.get("install") or {}, download, say)
            if rec:
                record["python_packages"].append(rec)
                record["components"].append({"slug": comp["slug"], "installed": rec})
            elif (comp.get("install") or {}).get("command"):
                record["components"].append({"slug": comp["slug"], "manual": comp["install"]["command"]})
    # 2. MCP servers (companion, generated tools, catalog servers)
    for m in manifest.get("mcp_servers", []):
        reg_info = m.get("registration") or {}
        if m.get("kind") == "companion":
            # Installed when absent, and upgraded when the server advertises a newer one. It used to
            # be installed only when missing, so a machine that had it once kept it for ever: the
            # server could ship a companion that knew about new tools, or carried corrected
            # instructions, and every install here went on registering the old one. The manifest has
            # carried `version` all along — nothing was comparing it.
            have = shutil.which("autoskill-companion")
            wanted = m.get("version")
            if m.get("download") and (not have or _is_newer(wanted, __version__)):
                try:
                    _cmd, rec = _install_python_package("autoskill-companion", m["download"]["url"])
                    record["python_packages"].append(rec)
                    if have:
                        # The agent loaded the old code when it started and holds it until it restarts;
                        # on Windows it may even be holding the file we just replaced.
                        say(f"autoskill-local updated to {wanted} — restart your agent so it picks it up.")
                except (subprocess.CalledProcessError, OSError) as exc:  # pragma: no cover
                    _companion_install_failed(
                        exc, updating=bool(have), wanted=wanted, url=m["download"]["url"], say=say
                    )
            reg = _companion_registration(cfg, trial_token)
        else:
            command = reg_info.get("command") or m["name"]
            if not reg_info.get("url"):
                installed_cmd, rec = _install_component_package(m["name"], m.get("install") or {}, m.get("download"), say)
                if installed_cmd:
                    command = installed_cmd
                if rec:
                    record["python_packages"].append(rec)
            env = ask([e["name"] for e in reg_info.get("env_requirements", []) if e.get("name")])
            reg = McpRegistration(
                name=m["name"],
                command=None if reg_info.get("url") else command,
                args=list(reg_info.get("args", [])),
                url=reg_info.get("url"),
                env=env,
            )
        record["mcp"].append(t.register_mcp(reg))
    # 3. the skill itself
    data = _fetch_artifact(skill["download"])
    root = _single_root(_extract_zip(data))
    meta = json.loads((root / "autoskill.json").read_text()) if (root / "autoskill.json").exists() else {}
    record.update(t.install_skill(root, root.name))
    return root.name, meta, record


def _ask_env(prompt_names: list[str]) -> dict[str, str]:
    """Ask the terminal for each missing value. The default provider, and only one of several.

    Installing is otherwise a headless operation; this is the single point in it that needs a person
    at a keyboard, which is exactly what a caller with no terminal cannot supply. Hence `EnvProvider`:
    the CLI passes this, a browser extension passes values it collected in a form beforehand.
    """
    values: dict[str, str] = {}
    for name in prompt_names:
        if os.environ.get(name):
            values[name] = os.environ[name]
            continue
        value = typer.prompt(
            f"Value for {name} (stored only in your agent configuration)", default="", show_default=False
        )
        if value:
            values[name] = value
    return values


def env_from(values: Mapping[str, str]) -> EnvProvider:
    """A provider that answers from values already collected, and never blocks on a terminal.

    Names it was not given are simply absent, as with an unanswered prompt: an install must not stop
    because one optional value is missing, and the agent's own configuration is where a person can
    still fill it in.
    """

    def provide(names: list[str]) -> dict[str, str]:
        return {n: values[n] for n in names if values.get(n)}

    return provide


def required_env(manifest: dict[str, Any]) -> list[str]:
    """Every environment value this bundle will ask for, before anything is installed.

    A terminal can be prompted halfway through; a web page cannot. It has to know what to ask for
    while the person is still looking at it, which means reading the manifest rather than discovering
    the answer by starting an installation that then stops.
    """
    names: list[str] = []
    for m in manifest.get("mcp_servers", []):
        if (m.get("kind") == "companion") or (m.get("registration") or {}).get("url"):
            continue
        for e in (m.get("registration") or {}).get("env_requirements", []):
            if e.get("name") and e["name"] not in names:
                names.append(e["name"])
    for comp in manifest.get("components", []):
        for e in comp.get("env_requirements", []) or []:
            if e.get("name") and e["name"] not in names:
                names.append(e["name"])
    return names


def install_trial_bundle(
    cfg: LocalConfig,
    manifest_url: str,
    token: str,
    *,
    target: str | None = None,
    session: str | None = None,
    env_provider: EnvProvider | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Install a trial from its manifest and tell the server it landed. Returns what was installed.

    The body of `autoskill trial install --from`, lifted out so the browser's native host performs the
    same installation rather than a second implementation of it that drifts. It returns a value and
    raises `LocalError`; the command prints, which is the only difference between the two callers.
    """
    say = progress or (lambda _line: None)
    manifest = fetch_json(manifest_url)
    trial = manifest.get("trial") or {}
    session = session or trial.get("session_id")
    target = target or trial.get("target_agent") or manifest.get("default_target")
    if not session or not target:
        raise LocalError("not_a_trial_bundle", "this bundle names no trial session or agent")
    say(f"installing for {target}")
    folder, _meta, record = _install_from_manifest(
        cfg, manifest, target, token, env_provider=env_provider, progress=progress
    )
    version = manifest["skill"].get("version")
    _refresh_device(cfg)
    client = Client(cfg.server_url or manifest.get("server_url"), api_key=cfg.api_key, trial_token=token)
    client.post(
        f"/trials/{session}/installed",
        {"install_manifest": record, "build": manifest["skill"].get("build", 1)},
    )
    cfg.trials[session] = {"token": token, "target": target, "skill": folder, "version": version, "manifest": record}
    cfg.save()
    say(f"{folder} v{version} installed")
    return {"session": session, "skill": folder, "version": version, "target": target}


@trial_app.command("install")
def trial_install(
    skill: str | None = typer.Argument(None, help="skill-name@version (legacy form; prefer --from)"),
    target: str | None = typer.Option(None, "--target"),
    session: str | None = typer.Option(None, "--session", help="trial session id from the web UI"),
    token: str = typer.Option(..., "--token", help="trial session token from the web UI"),
    from_url: str | None = typer.Option(None, "--from", help="install.json URL shown in the AutoSkill trial page"),
) -> None:
    """Install a trial copy of a skill, its MCP servers and shared components on your agent."""
    cfg = _cfg()
    if from_url:
        result = install_trial_bundle(cfg, from_url, token, target=target, session=session)
        typer.secho(
            f"Trial copy of {result['skill']} v{result['version']} installed for "
            f"{get_target(result['target']).display_name}.",
            fg=typer.colors.GREEN,
        )
        typer.echo(
            "Now open the trial page in AutoSkill and ask your agent to run the skill; every step will "
            "wait for your decision there."
        )
        return
    # The legacy form, kept for a bundle URL nobody has: it downloads the package from the trial
    # itself rather than from a manifest.
    if not from_url:
        if not skill or not target or not session:
            _fail("give --from <install.json url>, or skill@version with --target and --session")
        client = _client(cfg, trial_token=token)
        _name, _, version = skill.partition("@")
        root, meta, folder = _download_package(client, f"/trials/{session}/package.zip")
        record = _install(cfg, target, root, meta, folder, token, {})
        version = meta.get("version", version)
        build = meta.get("build", 1)
    _refresh_device(cfg)
    client.post(f"/trials/{session}/installed", {"install_manifest": record, "build": build})
    cfg.trials[session] = {"token": token, "target": target, "skill": folder, "version": version, "manifest": record}
    cfg.save()
    typer.secho(
        f"Trial copy of {folder} v{version} installed for {get_target(target).display_name}.", fg=typer.colors.GREEN
    )
    typer.echo(
        "Now open the trial page in AutoSkill and ask your agent to run the skill; every step will wait for your decision there."
    )


@trial_app.command("status")
def trial_status() -> None:
    cfg = _cfg()
    if not cfg.trials:
        typer.echo("no open trial on this machine")
        return
    for sid, info in cfg.trials.items():
        try:
            state = _client(cfg, trial_token=info["token"]).get(f"/trials/{sid}/sync")
            typer.echo(
                f"{info['skill']}@{info['version']} on {info['target']}: {state['state']} (build {state['installed_build']}/{state['current_build']}{', update available' if state['stale'] else ''})"
            )
        except ServerError as exc:
            typer.echo(f"{info['skill']}: {exc}")


@trial_app.command("sync")
def trial_sync(session: str | None = typer.Argument(None), watch: bool = False) -> None:
    """Update trial copies whose package changed on the server (after a step was corrected)."""
    cfg = _cfg()
    targets = [session] if session else list(cfg.trials)
    while True:
        for sid in targets:
            info = cfg.trials.get(sid)
            if not info:
                continue
            client = _client(cfg, trial_token=info["token"])
            state = client.get(f"/trials/{sid}/sync")
            if state["stale"]:
                manifest_url = (info.get("manifest") or {}).get("manifest_url")
                if manifest_url:
                    bundle = fetch_json(manifest_url)
                    folder, meta, manifest = _install_from_manifest(cfg, bundle, info["target"], info["token"])
                    meta = {"build": bundle["skill"].get("build")}
                else:
                    root, meta, folder = _download_package(client, f"/trials/{sid}/package.zip")
                    manifest = _install(cfg, info["target"], root, meta, folder, info["token"], {})
                client.post(f"/trials/{sid}/installed", {"install_manifest": manifest, "build": meta.get("build")})
                info["manifest"] = manifest
                cfg.save()
                typer.secho(f"{folder}: updated to build {meta.get('build')}", fg=typer.colors.GREEN)
            elif not watch:
                typer.echo(f"{info['skill']}: up to date (build {state['installed_build']})")
        if not watch:
            return
        time.sleep(5)


TRIAL_BANNER_START = "> ## "


def _strip_trial_markings(text: str) -> str:
    """Remove what only belonged to the trial: the frontmatter marker and the banner under the title.

    The fallback for when the definitive package cannot be fetched. It is deliberately narrow — the
    banner is a run of quoted lines that code wrote, immediately after the H1 — because guessing at
    somebody's document is how a promotion quietly corrupts a skill.
    """
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("autoskill_trial:")]
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith(TRIAL_BANNER_START) and "trial" in lines[i].lower():
            while i < len(lines) and (lines[i].startswith(">") or not lines[i].strip()):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out).rstrip() + "\n"


def _promote_to_permanent(
    cfg: LocalConfig, skill_dir: Path, version_id: str | None, name: str, say: Progress = typer.echo
) -> None:
    """Replace the trial copy with the version the server ships for an ordinary installation.

    A trial copy is not the same document. It opens with a banner telling the agent to walk every step
    through checkpoints and — the part that matters here — to stop and refuse the work if the companion
    is not available. That is right for a trial and wrong for a skill somebody now expects to just run:
    keeping it made an accepted skill dependent on the trial machinery it was supposed to graduate from.

    Fetching the real package rather than editing the trial one also picks up whatever else the server
    now generates, and leaves nothing behind that a text edit might have missed. The backup of what was
    there before the trial is not touched: this replaces the trial copy only.
    """
    fetched = None
    if version_id:
        try:
            data = _client(cfg).get(f"/versions/{version_id}/package.zip")
            fetched = _single_root(_extract_zip(data))
        except (ServerError, OSError, RuntimeError, ValueError) as exc:
            say(f"(could not fetch the final package: {exc})")
    if fetched is not None:
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        skill_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(fetched, skill_dir)
        return
    md = skill_dir / "SKILL.md"
    if md.exists():
        md.write_text(_strip_trial_markings(md.read_text()))
        say(f"{name}: kept the trial copy with its trial instructions removed.")


def _report_outcome(cfg: LocalConfig, sid: str, token: str, outcome: str, keep: bool) -> bool:
    """Tell the server the outcome, and cope with it already knowing. Returns the keep to act on.

    The outcome is normally decided in the browser, and the page then asks the person to run this
    command — which posted the outcome a second time and died on `409 trial_not_open`, with a
    traceback, having done none of the local work it exists for. The server refusing to decide a
    closed trial twice is right; treating that as failure was not, because deciding was never this
    command's real job. Copying files and rewriting the agent's configuration is, and that is exactly
    the part the browser cannot do.

    So a closed trial is read back instead: whatever was decided there is what happens here, and a
    `--keep` typed at a trial the person already removed in the page does not quietly resurrect it.
    """
    try:
        _client(cfg, trial_token=token).post(f"/trials/{sid}/outcome", {"outcome": outcome, "keep_installed": keep})
        return keep
    except ServerError as exc:
        if exc.code not in ("trial_not_open", "trial_closed"):
            raise
        try:
            trial = _client(cfg).get(f"/trials/{sid}")["trial"]
        except (ServerError, OSError):
            typer.secho("This trial is already closed on the server; settling the local copy.", fg=typer.colors.YELLOW)
            return keep
        decided, kept = trial.get("outcome"), trial.get("keep_installed")
        typer.secho(f"Already decided in AutoSkill as {decided!r}; settling the local copy to match.", fg=typer.colors.YELLOW)
        return keep if kept is None else bool(kept)


def _finish_trial(cfg: LocalConfig, sid: str, keep: bool, say: Progress | None = None) -> None:
    tell = say or typer.echo
    info = cfg.trials.pop(sid, None)
    if not info or not info.get("target"):
        # Settled with a token on a machine that never installed it: there is nothing here to promote
        # or delete, and pretending otherwise would either fail or remove somebody else's folder.
        tell(
            "The trial is settled in AutoSkill. Nothing was installed from this machine, so no local "
            "copy was touched; remove it on the machine that has it."
        )
        cfg.save()
        return
    t = get_target(info["target"])
    manifest = info.get("manifest", {})
    if keep:
        skill_dir = Path(manifest.get("skill_dir", t.skill_dir / info["skill"]))
        _promote_to_permanent(cfg, skill_dir, manifest.get("version_id"), info["skill"], tell)
        t.register_mcp(_companion_registration(cfg))  # re-registered without the trial token
        key = f"{info['target']}:{info['skill']}"
        cfg.installs[key] = {**manifest, "version": info.get("version")}
        tell(f"{info['skill']} kept as a permanent installation on {t.display_name}.")
        if manifest.get("version_id"):
            # Kept beside the rest of the record so `remove` has something to address later.
            cfg.installs[key]["installation_id"] = _register_installation(
                cfg, manifest["version_id"], info["target"], "cli", tell
            )
    else:
        t.remove_skill(info["skill"], manifest)
        _remove_bundle_parts(t, manifest)
        t.register_mcp(_companion_registration(cfg))  # keep the companion registered for other skills
        tell(f"{info['skill']} removed from {t.display_name}.")
    cfg.save()


def _remove_bundle_parts(t, manifest: dict[str, Any]) -> None:
    """Undo what _install_from_manifest did besides the skill folder: components, MCP registrations, venvs."""
    for comp in manifest.get("components", []):
        if comp.get("skill_dir"):
            t.remove_skill(comp["slug"], comp)
    for reg in manifest.get("mcp", []):
        if reg.get("name") and reg.get("name") != "autoskill-companion":
            t.unregister_mcp(reg["name"], reg.get("previous"))
    for pkg in manifest.get("python_packages", []):
        if pkg.get("method") == "venv" and pkg.get("path"):
            shutil.rmtree(pkg["path"], ignore_errors=True)
        # Uninstalling goes through `_run`, like installing: one place that spawns processes, so what
        # removal does can be seen and stubbed exactly where installation already could. `check=False`
        # is the difference that matters here — a package already gone must not stop the cleanup of
        # everything after it.
        elif pkg.get("method") == "pipx" and pkg.get("package") and shutil.which("pipx"):
            _run(["pipx", "uninstall", pkg["package"]], check=False)
        elif pkg.get("method") == "npm" and pkg.get("package") and shutil.which("npm"):
            _run(["npm", "uninstall", "-g", pkg["package"]], check=False)
        elif pkg.get("method") == "binary" and pkg.get("path"):
            Path(pkg["path"]).unlink(missing_ok=True)


def _trial_record(cfg: LocalConfig, session: str, token: str | None) -> dict:
    """The local record of a trial, or one rebuilt from a token given on the command line.

    Settling a trial used to require the machine to still hold its record, which is the normal case
    and not the only one: a config restored from elsewhere, a second machine, a person following the
    printed command on a laptop that never ran the install. The token in that command is what proves
    the right to settle the trial, so accepting it here is what makes the printed line runnable
    wherever it is pasted. What is missing without a local record is only the manifest — the paths on
    disk — so the fall-back settles the server side and says the local copy has to go by hand.
    """
    info = cfg.trials.get(session)
    if info:
        return info
    if not token:
        _fail(f"unknown trial {session} on this machine; pass --token <trial-token> to settle it anyway")
    typer.secho("No local record of this trial; using the token given.", fg=typer.colors.YELLOW)
    return {"token": token, "target": "", "skill": "", "version": None, "manifest": {}}


@trial_app.command("accept")
def trial_accept(
    session: str,
    keep: bool = typer.Option(True, "--keep/--remove"),
    token: str | None = typer.Option(None, "--token", help="trial token, when this machine has no record of it"),
) -> None:
    """Tell AutoSkill the trial is accepted; keep the copy as permanent or remove it."""
    cfg = _cfg()
    info = _trial_record(cfg, session, token)
    keep = _report_outcome(cfg, session, info["token"], "accepted", keep)
    _finish_trial(cfg, session, keep)


@trial_app.command("remove")
def trial_remove(
    session: str,
    outcome: str = typer.Option("removed", help="removed | major_rework | changes_requested"),
    token: str | None = typer.Option(None, "--token", help="trial token, when this machine has no record of it"),
) -> None:
    """Remove the trial copy and report the outcome."""
    cfg = _cfg()
    info = _trial_record(cfg, session, token)
    try:
        _report_outcome(cfg, session, info["token"], outcome, keep=False)
    except ServerError as exc:
        typer.echo(f"server: {exc} (removing locally anyway)")
    _finish_trial(cfg, session, keep=False)


@app.command()
def install(
    skill: str | None = typer.Argument(None, help="version id or skill-name@version (prefer --from)"),
    target: str | None = typer.Option(None, "--target"),
    version_id: str | None = typer.Option(None, "--version-id"),
    from_url: str | None = typer.Option(None, "--from", help="install.json URL from the Install tab or the hub"),
) -> None:
    """Permanently install a published/tested version, with its MCP servers and shared components."""
    cfg = _cfg()
    _refresh_device(cfg)
    if from_url:
        manifest = fetch_json(from_url)
        target = target or manifest.get("default_target") or "hermes"
        folder, _meta, record = _install_from_manifest(cfg, manifest, target, None)
        vid = manifest["skill"].get("version_id")
        version = manifest["skill"].get("version")
        if not cfg.server_url:
            cfg.server_url = manifest.get("server_url")
    else:
        if not target:
            _fail("give --target (or use --from <install.json url>)")
        client = _client(cfg)
        vid = version_id or (skill if skill and "@" not in skill else None)
        if vid is None:
            _fail("give a version id (see the Install tab in AutoSkill) with --version-id, or use --from")
        root, meta, folder = _download_package(client, f"/versions/{vid}/package.zip?targets={target}")
        record = _install(cfg, target, root, meta, folder, None, {})
        vid = meta.get("version_id", vid)
        version = meta.get("version")
    t = get_target(target)
    key = f"{target}:{folder}"
    cfg.installs[key] = {**record, "version_id": vid}
    if cfg.api_key and vid:
        cfg.installs[key]["installation_id"] = _register_installation(cfg, vid, target, "cli")
    cfg.save()
    typer.secho(
        f"{folder} v{version} installed for {t.display_name}. Restart the agent to load it.", fg=typer.colors.GREEN
    )


@app.command("remove")
def remove(skill: str, target: str = typer.Option(..., "--target")) -> None:
    cfg = _cfg()
    key = f"{target}:{skill}"
    manifest = cfg.installs.pop(key, None) or {}
    t = get_target(target)
    t.remove_skill(skill, manifest)
    _remove_bundle_parts(t, manifest)
    _report_removal(cfg, manifest, target)
    cfg.save()
    typer.echo(f"{skill} removed from {target}")


mcp_app = typer.Typer(help="Generated MCP servers bundled with skills.")
app.add_typer(mcp_app, name="mcp")


def _find_mcp_dir(root: Path) -> Path | None:
    mcp_root = root / "mcp"
    if not mcp_root.exists():
        return None
    for child in sorted(mcp_root.iterdir()):
        if (child / "pyproject.toml").exists() and child.name != "autoskill-companion":
            return child
    return None


@mcp_app.command("check")
def mcp_check(
    path: str = typer.Argument(..., help="skill folder (contains mcp/<skill>-tools) or the server folder"),
    report_version: str | None = typer.Option(None, "--report", help="MCP version id to send the report to"),
) -> None:
    """Install the generated MCP server in a temporary environment, import its tools and list them."""
    root = Path(path).expanduser().resolve()
    server_dir = root if (root / "pyproject.toml").exists() else _find_mcp_dir(root)
    if server_dir is None:
        _fail(f"no generated MCP server found under {root}")
    venv = Path(tempfile.mkdtemp(prefix="autoskill-mcp-"))
    report: dict[str, Any] = {"server_dir": str(server_dir), "ok": False, "tools": [], "log": []}
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
        pip = venv / ("Scripts" if os.name == "nt" else "bin") / "pip"
        py = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
        inst = subprocess.run([str(pip), "install", "-q", str(server_dir)], capture_output=True, text=True, check=False)
        report["log"].append(inst.stderr[-2000:] if inst.returncode else "installed")
        if inst.returncode:
            raise RuntimeError("pip install failed")
        name = next(
            line.split("=", 1)[1].strip().strip('"')
            for line in (server_dir / "pyproject.toml").read_text().splitlines()
            if line.startswith("name")
        )
        pkg = name.replace("-", "_")
        listed = subprocess.run(
            [str(py), "-m", f"{pkg}.server", "--list-tools"], capture_output=True, text=True, timeout=60, check=False
        )
        report["log"].append(listed.stderr[-2000:] if listed.returncode else "listed")
        if listed.returncode:
            raise RuntimeError("server failed to list tools")
        report["tools"] = json.loads(listed.stdout.strip().splitlines()[-1])
        tests = subprocess.run(
            [str(py), "-m", "pytest", "-q", str(server_dir / "tests")],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        report["log"].append(tests.stdout[-2000:])
        report["tests_ok"] = tests.returncode == 0 or "no tests ran" in tests.stdout
        report["ok"] = True
        typer.secho(
            f"OK: {len(report['tools'])} tools: {', '.join(t['name'] for t in report['tools'])}", fg=typer.colors.GREEN
        )
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
    finally:
        shutil.rmtree(venv, ignore_errors=True)
    if report_version:
        cfg = _cfg()
        _client(cfg).post(f"/mcp/versions/{report_version}/trial-report", report)
        typer.echo("report sent to AutoSkill")
    if not report["ok"]:
        raise typer.Exit(code=1)


@app.command("list")
def list_installs() -> None:
    cfg = _cfg()
    for key, info in cfg.installs.items():
        typer.echo(f"{key}: v{info.get('version')} ({info.get('skill_dir')})")
    if not cfg.installs:
        typer.echo("no permanent installation recorded")


if __name__ == "__main__":
    app()


def main() -> None:
    """Entry point: report what the server said, rather than how the call stack got there."""
    try:
        app()
    except ServerError as exc:
        detail = ""
        if isinstance(exc.body, dict):
            detail = (exc.body.get("error") or {}).get("message") or ""
        typer.secho(f"{exc.code or 'error'}: {detail or exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None
