"""Create a personal variant (fork) of a hub skill in one of the user's projects."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict
from autoskill.db.base import utcnow
from autoskill.models.memory import SkillMemoryEntry
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillDependency, SkillVersion, StepDefinition
from autoskill.models.user import User
from autoskill.services.interview.service import unique_skill_name
from autoskill.services.memory.store import add_entry
from autoskill.services.packaging.skill_package import SkillPackage
from autoskill.services.packaging.store import load_package, store_package


async def fork_skill(
    session: AsyncSession,
    *,
    source: Skill,
    source_version: SkillVersion,
    target_project_id: str,
    actor: User,
    new_title: str | None,
    kind: str = "personal_variant",
) -> tuple[Skill, SkillVersion]:
    if source.project_id == target_project_id and kind == "personal_variant":
        raise Conflict("fork_same_project", message="Choose a different project for your variant.")
    name = await unique_skill_name(session, target_project_id, source.name)
    skill = Skill(
        project_id=target_project_id,
        name=name,
        title=(new_title or source.title)[:200],
        summary=source.summary,
        visibility="private",
        forked_from_skill_id=source.id,
        forked_from_version_id=source_version.id,
        fork_kind=kind,
        tags=list(source.tags),
        created_by=actor.id,
    )
    session.add(skill)
    await session.flush()
    src_pkg = load_package(source.name, source_version)
    pkg = SkillPackage(name=name)
    for path, content in src_pkg.files.items():
        pkg.files[path] = content
    fm = pkg.frontmatter()
    fm["name"] = name
    meta = dict(fm.get("metadata") or {})
    meta.update(
        {
            "version": "0.1.0",
            "autoskill_skill_id": skill.id,
            "autoskill_project": target_project_id,
            "forked_from": f"{source.name}@{source_version.version}",
            "build": "1",
        }
    )
    fm["metadata"] = meta
    pkg.set_frontmatter(fm)
    version = SkillVersion(
        skill_id=skill.id,
        version="0.1.0",
        major=0,
        minor=1,
        patch=0,
        state="draft",
        origin="fork",
        changelog=f"Variant of {source.title} v{source_version.version}",
        rationale=f"Forked by {actor.display_name} from {source.name}@{source_version.version}",
        validation_report=pkg.validate().as_dict(),
        created_by=actor.id,
        state_changed_at=utcnow(),
        is_current_draft=True,
        draft_spec=source_version.draft_spec,
        build=1,
    )
    session.add(version)
    await session.flush()
    store_package(version, pkg)
    steps = (
        (
            await session.execute(
                select(StepDefinition)
                .where(StepDefinition.skill_version_id == source_version.id)
                .order_by(StepDefinition.ordinal)
            )
        )
        .scalars()
        .all()
    )
    for s in steps:
        session.add(
            StepDefinition(
                skill_version_id=version.id,
                ordinal=s.ordinal,
                key=s.key,
                title=s.title,
                instruction=s.instruction,
                kind=s.kind,
                side_effects=s.side_effects,
                restore_strategy=s.restore_strategy,
                trial_mode=s.trial_mode,
                requires_explicit_auth=s.requires_explicit_auth,
                inputs=s.inputs,
                outputs=s.outputs,
                data_source_refs=s.data_source_refs,
                success_criteria=s.success_criteria,
                failure_modes=s.failure_modes,
                network=s.network,
                library_component_slug=s.library_component_slug,
            )
        )
    deps = (
        (await session.execute(select(SkillDependency).where(SkillDependency.skill_version_id == source_version.id)))
        .scalars()
        .all()
    )
    for d in deps:
        session.add(
            SkillDependency(
                skill_version_id=version.id,
                component_slug=d.component_slug,
                version_constraint=d.version_constraint,
                reason=d.reason,
            )
        )
    memory = (
        (
            await session.execute(
                select(SkillMemoryEntry).where(
                    SkillMemoryEntry.skill_id == source.id, SkillMemoryEntry.status == "active"
                )
            )
        )
        .scalars()
        .all()
    )
    for m in memory:
        await add_entry(
            session,
            skill.id,
            kind=m.kind,
            title=m.title,
            body=m.body,
            structured=m.structured,
            step_key=m.step_key,
            source="import",
            source_ref=m.id,
            tags=m.tags,
        )
    await add_entry(
        session,
        skill.id,
        kind="decision",
        title="Forked from the hub",
        body=f"Variant of {source.title} v{source_version.version}; adapt steps to local needs.",
        source="manual",
        author_user_id=actor.id,
    )
    skill.latest_version_id = version.id
    return skill, version
