"""Side effects of publishing a version: notify installers, refresh hub counters, git repo (Phase 5)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.events import emit, project_channel
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion
from autoskill.models.user import User


async def on_published(session: AsyncSession, skill: Skill, version: SkillVersion, actor: User) -> None:
    await emit(
        project_channel(skill.project_id),
        "version.published",
        {"skill_id": skill.id, "version_id": version.id, "version": version.version},
    )
    try:
        from autoskill.services.distribution.hub import after_publish

        await after_publish(session, skill, version, actor)
    except ImportError:  # hub not available yet
        pass
