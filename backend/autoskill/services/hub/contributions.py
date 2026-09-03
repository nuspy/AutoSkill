"""Contribute a variant back to the skill it was forked from.

Accepting creates a new draft version on the original (files, steps and dependencies copied from the
variant's version) that then follows the normal trial -> review -> publish flow; nothing is published.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.db.base import utcnow
from autoskill.models.hub import Contribution
from autoskill.models.project import ProjectMember
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillDependency, SkillVersion, StepDefinition
from autoskill.models.user import User
from autoskill.services.notifications import notify
from autoskill.services.packaging.skill_package import SkillPackage
from autoskill.services.packaging.store import load_package, store_package
from autoskill.services.versioning.semver import bump, parse


async def propose(
    session: AsyncSession, *, variant: Skill, version: SkillVersion, actor: User, message: str | None
) -> Contribution:
    if not variant.forked_from_skill_id:
        raise ValidationFailed("not_a_fork", message="Only variants forked from a hub skill can contribute back.")
    target = await session.get(Skill, variant.forked_from_skill_id)
    if target is None or target.archived_at is not None:
        raise NotFound("original_not_found")
    if version.skill_id != variant.id or version.state in ("draft", "discarded", "rejected"):
        raise Conflict(
            "version_not_contributable",
            message="Test the variant first: only tested or published versions can be proposed.",
        )
    open_one = (
        await session.execute(
            select(Contribution).where(
                Contribution.source_skill_id == variant.id,
                Contribution.target_skill_id == target.id,
                Contribution.state == "open",
            )
        )
    ).scalar_one_or_none()
    if open_one is not None:
        raise Conflict(
            "contribution_open", message="A contribution from this variant is already waiting for a decision."
        )
    row = Contribution(
        source_skill_id=variant.id,
        source_version_id=version.id,
        target_skill_id=target.id,
        proposed_by=actor.id,
        message=(message or "").strip()[:4000] or None,
    )
    session.add(row)
    await session.flush()
    members = (
        await session.execute(select(ProjectMember).where(ProjectMember.project_id == target.project_id))
    ).scalars()
    for m in members:
        if m.role.value in ("owner", "editor"):
            await notify(
                session,
                m.user_id,
                "contribution_received",
                f"{actor.display_name} proposes changes to {target.title}",
                body=row.message,
                subject_type="skill",
                subject_id=target.id,
                payload={"contribution_id": row.id, "variant_skill_id": variant.id},
            )
    return row


async def decide(
    session: AsyncSession, *, contribution: Contribution, actor: User, accept: bool, comment: str | None
) -> Contribution:
    if contribution.state != "open":
        raise Conflict("contribution_decided", state=contribution.state)
    contribution.decided_by = actor.id
    contribution.decided_at = utcnow()
    contribution.decision_comment = (comment or "").strip()[:4000] or None
    if not accept:
        contribution.state = "rejected"
    else:
        target = await session.get(Skill, contribution.target_skill_id)
        source_version = await session.get(SkillVersion, contribution.source_version_id)
        if target is None or source_version is None:
            raise NotFound("version_not_found")
        version = await _draft_from(session, target, source_version, contribution, actor)
        contribution.target_version_id = version.id
        contribution.state = "accepted"
    await notify(
        session,
        contribution.proposed_by,
        "contribution_decided",
        f"Your contribution was {contribution.state}",
        body=contribution.decision_comment,
        subject_type="skill",
        subject_id=contribution.source_skill_id,
        payload={"contribution_id": contribution.id, "target_version_id": contribution.target_version_id},
    )
    return contribution


async def _next_version(session: AsyncSession, skill: Skill) -> str:
    res = await session.execute(select(SkillVersion.version).where(SkillVersion.skill_id == skill.id))
    versions = [v for (v,) in res.all()]
    if not versions:
        return "0.1.0"
    latest = max(versions, key=parse)
    return bump(latest, "patch")


async def _draft_from(
    session: AsyncSession, target: Skill, source_version: SkillVersion, contribution: Contribution, actor: User
) -> SkillVersion:
    source_skill = await session.get(Skill, source_version.skill_id)
    src = load_package(source_skill.name if source_skill else target.name, source_version)
    pkg = SkillPackage(name=target.name)
    for path, content in src.files.items():
        pkg.files[path] = content
    fm = pkg.frontmatter()
    fm["name"] = target.name
    meta = dict(fm.get("metadata") or {})
    new_version = await _next_version(session, target)
    meta.update(
        {
            "version": new_version,
            "autoskill_skill_id": target.id,
            "autoskill_project": target.project_id,
            "contributed_from": f"{source_skill.name if source_skill else '?'}@{source_version.version}",
            "build": "1",
        }
    )
    meta.pop("autoskill_trial", None)
    fm["metadata"] = meta
    pkg.set_frontmatter(fm)
    major, minor, patch = parse(new_version)
    version = SkillVersion(
        skill_id=target.id,
        version=new_version,
        major=major,
        minor=minor,
        patch=patch,
        state="draft",
        origin="contribution",
        parent_version_id=target.current_published_version_id,
        changelog=f"Contribution from {source_skill.title if source_skill else 'a variant'} v{source_version.version}"
        + (f": {contribution.message}" if contribution.message else ""),
        rationale=f"Accepted by {actor.display_name}",
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
    for other in (
        await session.execute(
            select(SkillVersion).where(
                SkillVersion.skill_id == target.id,
                SkillVersion.is_current_draft.is_(True),
                SkillVersion.id != version.id,
            )
        )
    ).scalars():
        other.is_current_draft = False
    target.latest_version_id = version.id
    await session.flush()
    return version
