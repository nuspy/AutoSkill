"""Version comparison helpers: file diffs, step diffs and semver inference."""

from __future__ import annotations

import difflib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.services.packaging.skill_package import TEXT_EXTENSIONS
from autoskill.services.packaging.store import load_package


async def steps_of(session: AsyncSession, version_id: str) -> list[StepDefinition]:
    res = await session.execute(
        select(StepDefinition).where(StepDefinition.skill_version_id == version_id).order_by(StepDefinition.ordinal)
    )
    return list(res.scalars())


def _step_changed(n: StepDefinition, o: StepDefinition) -> bool:
    return n.instruction != o.instruction or n.kind != o.kind or n.side_effects != o.side_effects


def unified_diff(path: str, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}", n=3
        )
    )


async def compare(session: AsyncSession, skill: Skill, newer: SkillVersion, older: SkillVersion | None) -> dict:
    new_pkg = load_package(skill.name, newer)
    old_pkg = load_package(skill.name, older) if older else None
    files: list[dict] = []
    paths = sorted(set(new_pkg.files) | set(old_pkg.files if old_pkg else {}))
    for path in paths:
        new_bytes = new_pkg.files.get(path)
        old_bytes = old_pkg.files.get(path) if old_pkg else None
        if new_bytes == old_bytes:
            continue
        status = "added" if old_bytes is None else "removed" if new_bytes is None else "changed"
        text_diff = None
        if any(path.endswith(ext) for ext in TEXT_EXTENSIONS):
            text_diff = unified_diff(
                path, (old_bytes or b"").decode(errors="replace"), (new_bytes or b"").decode(errors="replace")
            )
        files.append({"path": path, "status": status, "diff": text_diff})
    new_steps = {s.key: s for s in await steps_of(session, newer.id)}
    old_steps = {s.key: s for s in await steps_of(session, older.id)} if older else {}
    steps = {
        "added": [k for k in new_steps if k not in old_steps],
        "removed": [k for k in old_steps if k not in new_steps],
        "changed": [
            k
            for k in new_steps
            if k in old_steps
            and (
                new_steps[k].instruction != old_steps[k].instruction
                or new_steps[k].kind != old_steps[k].kind
                or new_steps[k].side_effects != old_steps[k].side_effects
            )
        ],
        "reordered": [k for k, s in new_steps.items() if k in old_steps and s.ordinal != old_steps[k].ordinal],
    }
    return {
        "from": older.version if older else None,
        "to": newer.version,
        "files": files,
        "steps": steps,
        "suggested_bump": infer_bump(files, steps, new_steps, old_steps),
    }


def infer_bump(files: list[dict], steps: dict, new_steps: dict, old_steps: dict) -> str:
    """Infer the semver bump.

    major: data sources / side effects / IO change; minor: step added, removed or reordered,
    new reference; patch: wording only.
    """
    if not old_steps:
        return "minor"
    for k in steps["changed"]:
        n, o = new_steps[k], old_steps[k]
        if (
            n.side_effects != o.side_effects
            or n.inputs != o.inputs
            or n.outputs != o.outputs
            or set(n.data_source_refs) != set(o.data_source_refs)
        ):
            return "major"
    if steps["removed"]:
        return "major"
    if (
        steps["added"]
        or steps["reordered"]
        or any(f["status"] == "added" and f["path"].startswith("references/") for f in files)
    ):
        return "minor"
    return "patch"
