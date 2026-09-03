"""`autoskill` command line: login, trial install/sync/accept/remove, install/remove/list, doctor."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import platform
import shutil
import socket
import tempfile
import time
import webbrowser
import zipfile
from pathlib import Path
from typing import Any

import typer

from autoskill_local import __version__
from autoskill_local.client import Client, ServerError, fetch_json, fetch_url
from autoskill_local.config import HOME, LocalConfig
from autoskill_local.targets import detect_targets, get_target
from autoskill_local.targets.base import McpRegistration

app = typer.Typer(help="AutoSkill on your machine: install and trial skills on your own agent.", no_args_is_help=True)
trial_app = typer.Typer(help="Temporary installations tested step by step with AutoSkill.")
app.add_typer(trial_app, name="trial")


def _cfg() -> LocalConfig:
    return LocalConfig.load()


def _client(cfg: LocalConfig | None = None, trial_token: str | None = None) -> Client:
    cfg = cfg or _cfg()
    if not cfg.server_url:
        raise typer.BadParameter("not logged in: run `autoskill login <server-url>` first")
    return Client(cfg.server_url, api_key=cfg.api_key, trial_token=trial_token)


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


@app.command()
def doctor() -> None:
    """Show detected agents, configuration and companion registration."""
    cfg = _cfg()
    typer.echo(
        f"server: {cfg.server_url or '-'}   logged in: {'yes' if cfg.api_key else 'no'}   device: {cfg.device_id or '-'}"
    )
    found = detect_targets()
    typer.echo("agents detected: " + (", ".join(found) or "none"))
    for tid in found:
        t = get_target(tid)
        regs = t.registered_mcps()
        typer.echo(
            f"  {t.display_name}: skills in {t.skill_dir}  companion: {'registered' if 'autoskill-companion' in regs else 'missing'}"
        )
    if cfg.trials:
        typer.echo(
            "open trials: " + ", ".join(f"{v['skill']}@{v['version']} ({v['target']})" for v in cfg.trials.values())
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


def _register_installation(cfg: LocalConfig, version_id: str, target: str, channel: str) -> None:
    """Tell the server this machine installed the version (enables update alerts); never fatal."""
    try:
        _client(cfg).post(
            "/me/installations",
            {
                "skill_version_id": version_id,
                "target_agent": target,
                "channel": channel,
                "state": "installed",
                "device_id": cfg.device_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"(could not register the installation with AutoSkill: {exc})")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch_artifact(ref: dict[str, Any]) -> bytes:
    """Download an artifact of the bundle and verify its checksum when the bundle gives one."""
    data = fetch_url(ref["url"])
    expected = ref.get("sha256")
    if expected and _sha256(data) != expected:
        raise RuntimeError(f"checksum mismatch for {ref['url']}: refusing to install")
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


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


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


def _install_from_manifest(
    cfg: LocalConfig, manifest: dict[str, Any], target: str, trial_token: str | None
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Install everything an install.json bundle lists, in order: components, MCP servers, skill.

    Returns (skill folder name, skill metadata, install manifest for a clean removal)."""
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
            if dest and Path(dest).expanduser() != Path(info["skill_dir"]):
                # the catalog asked for a specific folder on this agent
                target_dir = Path(dest).expanduser()
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(info["skill_dir"], target_dir)
                info["skill_dir"] = str(target_dir)
            record["components"].append({"slug": comp["slug"], **info})
            typer.echo(f"component {comp['slug']} installed in {info['skill_dir']}")
        elif (comp.get("install") or {}).get("command"):
            typer.echo(f"component {comp['slug']}: run `{comp['install']['command']}` (not automated)")
            record["components"].append({"slug": comp["slug"], "manual": comp["install"]["command"]})
    # 2. MCP servers (companion, generated tools, catalog servers)
    for m in manifest.get("mcp_servers", []):
        reg_info = m.get("registration") or {}
        if m.get("kind") == "companion":
            if not shutil.which("autoskill-companion") and m.get("download"):
                try:
                    cmd, rec = _install_python_package("autoskill-companion", m["download"]["url"])
                    record["python_packages"].append(rec)
                except (subprocess.CalledProcessError, OSError) as exc:  # pragma: no cover
                    typer.echo(f"(could not install autoskill-local automatically: {exc})")
            reg = _companion_registration(cfg, trial_token)
        else:
            command = reg_info.get("command") or m["name"]
            method = (m.get("install") or {}).get("method")
            if m.get("download") and method in ("pipx_archive", "pipx", "pip"):
                data = _fetch_artifact(m["download"])
                archive = Path(tempfile.mkdtemp(prefix="autoskill-mcp-")) / m["download"]["filename"]
                archive.write_bytes(data)
                command, rec = _install_python_package(m["name"], str(archive))
                record["python_packages"].append(rec)
            elif method in ("pipx", "pip") and (m.get("install") or {}).get("spec"):
                command, rec = _install_python_package(m["name"], m["install"]["spec"])
                record["python_packages"].append(rec)
            elif (m.get("install") or {}).get("command") and not reg_info.get("url"):
                typer.echo(f"MCP {m['name']}: install it first with `{m['install']['command']}`")
            env = _ask_env([e["name"] for e in reg_info.get("env_requirements", []) if e.get("name")])
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
        manifest = fetch_json(from_url)
        trial = manifest.get("trial") or {}
        session = session or trial.get("session_id")
        target = target or trial.get("target_agent") or manifest.get("default_target")
        if not session or not target:
            _fail("this bundle is not a trial bundle: give --session and --target")
        server = cfg.server_url or manifest.get("server_url")
        client = Client(server, api_key=cfg.api_key, trial_token=token)
        folder, _meta, record = _install_from_manifest(cfg, manifest, target, token)
        version = manifest["skill"].get("version")
        build = manifest["skill"].get("build", 1)
    else:
        if not skill or not target or not session:
            _fail("give --from <install.json url>, or skill@version with --target and --session")
        client = _client(cfg, trial_token=token)
        _name, _, version = skill.partition("@")
        root, meta, folder = _download_package(client, f"/trials/{session}/package.zip")
        record = _install(cfg, target, root, meta, folder, token, {})
        version = meta.get("version", version)
        build = meta.get("build", 1)
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


def _finish_trial(cfg: LocalConfig, sid: str, keep: bool) -> None:
    info = cfg.trials.pop(sid, None)
    if not info:
        _fail(f"unknown trial {sid}")
    t = get_target(info["target"])
    manifest = info.get("manifest", {})
    if keep:
        # promote: drop the trial marker and the trial token from the companion env
        skill_dir = Path(manifest.get("skill_dir", t.skill_dir / info["skill"]))
        md = skill_dir / "SKILL.md"
        if md.exists():
            text = md.read_text()
            md.write_text(
                "\n".join(line for line in text.splitlines() if not line.strip().startswith("autoskill_trial:")) + "\n"
            )
        t.register_mcp(_companion_registration(cfg))
        cfg.installs[f"{info['target']}:{info['skill']}"] = {**manifest, "version": info.get("version")}
        typer.secho(f"{info['skill']} kept as a permanent installation on {t.display_name}.", fg=typer.colors.GREEN)
        if manifest.get("version_id"):
            _register_installation(cfg, manifest["version_id"], info["target"], "cli")
    else:
        t.remove_skill(info["skill"], manifest)
        _remove_bundle_parts(t, manifest)
        t.register_mcp(_companion_registration(cfg))  # keep the companion registered for other skills
        typer.secho(f"{info['skill']} removed from {t.display_name}.", fg=typer.colors.GREEN)
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
        elif pkg.get("method") == "pipx" and pkg.get("package") and shutil.which("pipx"):
            subprocess.run(["pipx", "uninstall", pkg["package"]], check=False, capture_output=True)


@trial_app.command("accept")
def trial_accept(session: str, keep: bool = typer.Option(True, "--keep/--remove")) -> None:
    """Tell AutoSkill the trial is accepted; keep the copy as permanent or remove it."""
    cfg = _cfg()
    info = cfg.trials.get(session)
    if not info:
        _fail(f"unknown trial {session}")
    _client(cfg, trial_token=info["token"]).post(
        f"/trials/{session}/outcome", {"outcome": "accepted", "keep_installed": keep}
    )
    _finish_trial(cfg, session, keep)


@trial_app.command("remove")
def trial_remove(
    session: str, outcome: str = typer.Option("removed", help="removed | major_rework | changes_requested")
) -> None:
    """Remove the trial copy and report the outcome."""
    cfg = _cfg()
    info = cfg.trials.get(session)
    if not info:
        _fail(f"unknown trial {session}")
    try:
        _client(cfg, trial_token=info["token"]).post(
            f"/trials/{session}/outcome", {"outcome": outcome, "keep_installed": False}
        )
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
        record = _install(cfg, target, root, meta, folder, None, _ask_env([]))
        vid = meta.get("version_id", vid)
        version = meta.get("version")
    t = get_target(target)
    cfg.installs[f"{target}:{folder}"] = {**record, "version_id": vid}
    cfg.save()
    if cfg.api_key and vid:
        _register_installation(cfg, vid, target, "cli")
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
