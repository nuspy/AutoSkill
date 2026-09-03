"""After a version is published: hub timestamps, installer notifications, git repository."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.config import get_settings
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
        from autoskill.api.v1.versions import _install_context
        from autoskill.services.targets import get_adapter

        pkg = load_package(skill.name, version)
        files = dict(pkg.files)
        ctx = await _install_context(session, skill, version)
        ctx.git_url = f"{get_settings().public_url.split('://', 1)[-1]}/git/{project.slug}/{skill.name}.git"
        for target in list_targets():
            files[f"INSTALL.{target['id']}.md"] = get_adapter(target["id"]).render_install_md(ctx).encode()
        files["autoskill.json"] = json.dumps(
            {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "version_id": version.id,
                "version": version.version,
                "server_url": get_settings().public_url,
            },
            indent=2,
        ).encode()
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
    except Exception as exc:  # noqa: BLE001 - git problems must not block publishing
        log.exception("git publish failed for %s: %s", skill.name, exc)
