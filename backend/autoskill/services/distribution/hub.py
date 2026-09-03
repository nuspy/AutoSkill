"""After a version is published: hub timestamps, installer notifications, git repository."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.db.base import utcnow
from autoskill.models.hub import Installation, SkillRepo
from autoskill.models.project import Project
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion
from autoskill.models.user import User
from autoskill.services.distribution import git_repo
from autoskill.services.notifications import notify
from autoskill.services.packaging.store import load_package
from autoskill.services.targets import list_targets

log = logging.getLogger(__name__)

# (skill_id, version_id) pairs whose external mirror push must be enqueued once the publish is committed
pending_external_pushes: list[dict] = []


async def flush_external_pushes(project_id: str | None = None) -> int:
    """Enqueue the mirror pushes recorded by after_publish (call after the transaction is committed)."""
    from autoskill.core.jobs import get_job_runner

    count = 0
    while pending_external_pushes:
        item = pending_external_pushes.pop(0)
        await get_job_runner().enqueue("distribution.push_external", item, project_id=project_id, user_id=None)
        count += 1
    return count


async def after_publish(session: AsyncSession, skill: Skill, version: SkillVersion, actor: User) -> None:
    skill.published_at = utcnow()
    # notify people with an older installation
    res = await session.execute(
        select(Installation).where(
            Installation.skill_id == skill.id,
            Installation.state != "removed",
            Installation.skill_version_id != version.id,
        )
    )
    seen: set[str] = set()
    for inst in res.scalars():
        if inst.user_id in seen:
            continue
        seen.add(inst.user_id)
        await notify(
            session,
            inst.user_id,
            "skill_update_available",
            f"Update available: {skill.title} v{version.version}",
            body=version.changelog,
            subject_type="skill",
            subject_id=skill.id,
            payload={"version_id": version.id, "version": version.version},
        )
    # git repository
    if not git_repo.git_available():
        log.warning("git not available; skipping repository publish for %s", skill.name)
        return
    project = await session.get(Project, skill.project_id)
    if project is None:
        return
    try:
        from autoskill.services.distribution import bundle as bundles

        pkg = load_package(skill.name, version)
        files = dict(pkg.files)
        bundle = await bundles.build_bundle(
            session,
            skill=skill,
            version=version,
            base_url=bundles.hub_base_url(project.slug, skill.name, version.version),
            kind="hub",
        )
        for target in list_targets():
            files[f"INSTALL.{target['id']}.md"] = bundles.render_install_md(bundle, target["id"], project.slug).encode()
        files["autoskill.json"] = bundles.bundle_json(bundle)
        sha = git_repo.publish_to_repo(
            project.slug,
            skill.name,
            version.version,
            files,
            f"{skill.name} v{version.version}\n\n{version.changelog or ''}".strip(),
        )
        repo = await session.get(SkillRepo, skill.id)
        if repo is None:
            repo = SkillRepo(
                skill_id=skill.id,
                path=str(git_repo.repo_path(project.slug, skill.name)),
                public_clone=skill.visibility == "public",
            )
            session.add(repo)
        repo.head_version_id = version.id
        repo.last_pushed_at = utcnow()
        repo.public_clone = skill.visibility == "public"
        log.info("published %s v%s to git (%s)", skill.name, version.version, sha[:8])
        if repo.external_remote_url:
            pending_external_pushes.append({"skill_id": skill.id, "version_id": version.id})
    except Exception as exc:  # noqa: BLE001 - git problems must not block publishing
        log.exception("git publish failed for %s: %s", skill.name, exc)
