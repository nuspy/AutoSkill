"""One bare git repository per published skill so `openclaw skills install git:...` and `git clone` work.

The repository root is the skill folder (SKILL.md at the top level) plus INSTALL.*.md and
autoskill.json. Each publish commits on `main` and tags `v<semver>`. Read-only smart HTTP is served by
`serve.py` through `git upload-pack --stateless-rpc`; pushes are never accepted.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from autoskill.config import get_settings

GIT = shutil.which("git")


def repo_root() -> Path:
    return get_settings().data_dir / "store" / "git"


def repo_path(project_slug: str, skill_name: str) -> Path:
    return repo_root() / project_slug / f"{skill_name}.git"


def git_available() -> bool:
    return GIT is not None


def _run(args: list[str], cwd: Path | None = None, env: dict | None = None, input_bytes: bytes | None = None) -> bytes:
    assert GIT is not None
    res = subprocess.run(
        [GIT, *args], cwd=cwd, env={**os.environ, **(env or {})}, input=input_bytes, capture_output=True, check=False
    )
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.decode(errors='replace')[:500]}")
    return res.stdout


def publish_to_repo(project_slug: str, skill_name: str, version: str, files: dict[str, bytes], message: str) -> str:
    """Commit `files` as the new tree on main and tag v<version>. Returns the commit sha."""
    if GIT is None:
        raise RuntimeError("git executable not available")
    bare = repo_path(project_slug, skill_name)
    if not bare.exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        _run(["init", "--bare", "--initial-branch=main", str(bare)])
        _run(["config", "http.receivepack", "false"], cwd=bare)
    work = Path(tempfile.mkdtemp(prefix="autoskill-git-"))
    try:
        _run(["clone", "--quiet", str(bare), str(work / "w")])
        wt = work / "w"
        for item in wt.iterdir():
            if item.name == ".git":
                continue
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        for rel, content in files.items():
            dest = wt / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        env = {
            "GIT_AUTHOR_NAME": "AutoSkill",
            "GIT_AUTHOR_EMAIL": "autoskill@localhost",
            "GIT_COMMITTER_NAME": "AutoSkill",
            "GIT_COMMITTER_EMAIL": "autoskill@localhost",
        }
        _run(["checkout", "-q", "-B", "main"], cwd=wt, env=env)
        _run(["add", "-A"], cwd=wt, env=env)
        _run(["commit", "-q", "--allow-empty", "-m", message], cwd=wt, env=env)
        _run(["tag", "-f", f"v{version}"], cwd=wt, env=env)
        _run(["push", "-q", "--force", "origin", "main", f"refs/tags/v{version}"], cwd=wt, env=env)
        return _run(["rev-parse", "HEAD"], cwd=wt).decode().strip()
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def advertise_refs(bare: Path) -> bytes:
    """Body of GET /info/refs?service=git-upload-pack (smart HTTP)."""

    def go() -> bytes:
        head = b"# service=git-upload-pack\n"
        pkt = f"{len(head) + 4:04x}".encode() + head + b"0000"
        return pkt + _run(["upload-pack", "--stateless-rpc", "--advertise-refs", str(bare)])

    return await asyncio.to_thread(go)


async def upload_pack(bare: Path, body: bytes) -> bytes:
    """Body of POST /git-upload-pack."""
    return await asyncio.to_thread(lambda: _run(["upload-pack", "--stateless-rpc", str(bare)], input_bytes=body))


def list_tags(bare: Path) -> list[str]:
    return [t for t in _run(["tag", "--list"], cwd=bare).decode().split("\n") if t]
