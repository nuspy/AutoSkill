"""`autoskill` command line: login, trial install/sync/accept/remove, install/remove/list, doctor."""

from __future__ import annotations

import io
import json
import os
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
from autoskill_local.client import Client, ServerError
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
    skill: str = typer.Argument(..., help="skill-name@version"),
    target: str = typer.Option(..., "--target"),
    session: str = typer.Option(..., "--session", help="trial session id from the web UI"),
    token: str = typer.Option(..., "--token", help="trial session token from the web UI"),
) -> None:
    """Install a trial copy of a skill and its MCP servers on your agent."""
    cfg = _cfg()
    client = _client(cfg, trial_token=token)
    _name, _, ver = skill.partition("@")
    root, meta, folder = _download_package(client, f"/trials/{session}/package.zip")
    manifest = _install(cfg, target, root, meta, folder, token, {})
    client.post(f"/trials/{session}/installed", {"install_manifest": manifest, "build": meta.get("build", 1)})
    cfg.trials[session] = {
        "token": token,
        "target": target,
        "skill": folder,
        "version": meta.get("version", ver),
        "manifest": manifest,
    }
    cfg.save()
    typer.secho(
        f"Trial copy of {folder} v{meta.get('version', ver)} installed for {get_target(target).display_name}.",
        fg=typer.colors.GREEN,
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
    else:
        t.remove_skill(info["skill"], manifest)
        for reg in manifest.get("mcp", []):
            if reg.get("name") == "autoskill-companion" and reg.get("previous") is None:
                continue  # keep the companion registered for other skills
        t.register_mcp(_companion_registration(cfg))
        typer.secho(f"{info['skill']} removed from {t.display_name}.", fg=typer.colors.GREEN)
    cfg.save()


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
    skill: str = typer.Argument(..., help="version id or skill-name@version"),
    target: str = typer.Option(..., "--target"),
    version_id: str | None = typer.Option(None, "--version-id"),
) -> None:
    """Permanently install a published/tested version on your agent."""
    cfg = _cfg()
    client = _client(cfg)
    vid = version_id or (skill if "@" not in skill else None)
    if vid is None:
        _fail("give a version id (see the Install tab in AutoSkill) with --version-id")
    root, meta, folder = _download_package(client, f"/versions/{vid}/package.zip?targets={target}")
    t = get_target(target)
    env_names = []
    manifest = _install(cfg, target, root, meta, folder, None, _ask_env(env_names))
    cfg.installs[f"{target}:{folder}"] = {**manifest, "version_id": vid}
    cfg.save()
    typer.secho(
        f"{folder} v{meta.get('version')} installed for {t.display_name}. Restart the agent to load it.",
        fg=typer.colors.GREEN,
    )


@app.command("remove")
def remove(skill: str, target: str = typer.Option(..., "--target")) -> None:
    cfg = _cfg()
    key = f"{target}:{skill}"
    manifest = cfg.installs.pop(key, None)
    get_target(target).remove_skill(skill, manifest or {})
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
    import subprocess
    import sys

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
