"""Re-assemble a version's package after a step instruction changes, bumping the build number."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.models.trial import TrialSession
from autoskill.schemas.draft import DraftSpec
from autoskill.services.drafting.assemble import assemble_package
from autoskill.services.packaging.store import store_package


async def rebuild_package(session: AsyncSession, version: SkillVersion) -> None:
    if not version.draft_spec:
        raise Conflict("version_not_rebuildable", message="This version has no draft spec to rebuild from.")
    skill = await session.get(Skill, version.skill_id)
    if skill is None:
        raise NotFound("skill_not_found")
    spec = DraftSpec.model_validate(version.draft_spec)
    res = await session.execute(
        select(StepDefinition).where(StepDefinition.skill_version_id == version.id).order_by(StepDefinition.ordinal)
    )
    by_key = {s.key: s for s in res.scalars()}
    for step in spec.steps:
        if step.key in by_key:
            step.instruction = by_key[step.key].instruction
            step.success_criteria = by_key[step.key].success_criteria or ""
    metadata = {
        k: v
        for k, v in (version.frontmatter.get("metadata") or {}).items()
        if k not in ("version", "language", "build")
    }
    version.build += 1
    metadata["build"] = str(version.build)
    from autoskill.models.mcp import McpServerVersion

    mv = (
        await session.execute(select(McpServerVersion).where(McpServerVersion.skill_version_id == version.id))
    ).scalar_one_or_none()
    pkg = assemble_package(
        skill_name=skill.name,
        version=version.version,
        spec=spec,
        metadata=metadata,
        language=(version.frontmatter.get("metadata") or {}).get("language", "en"),
        tools=mv.tools if mv else None,
        server_name=f"{skill.name}-tools" if mv else None,
    )
    report = pkg.validate()
    if not report.ok:
        raise Conflict("rebuild_validation_failed", issues=[i.message for i in report.errors])
    version.draft_spec = spec.model_dump()
    version.validation_report = report.as_dict()
    store_package(version, pkg)
    # active trials on this version must sync their installed copy
    res = await session.execute(
        select(TrialSession).where(
            TrialSession.skill_version_id == version.id, TrialSession.state.in_(("installed", "testing", "suspended"))
        )
    )
    for trial in res.scalars():
        trial.build = version.build


async def patch_step_instruction(
    session: AsyncSession, version_id: str, step_key: str, new_instruction: str, note: str | None = None
) -> StepDefinition:
    version = await session.get(SkillVersion, version_id)
    if version is None:
        raise NotFound("version_not_found")
    if version.state not in ("draft", "testing", "changes_requested"):
        raise Conflict("version_not_editable", state=version.state)
    res = await session.execute(
        select(StepDefinition).where(StepDefinition.skill_version_id == version_id, StepDefinition.key == step_key)
    )
    step = res.scalar_one_or_none()
    if step is None:
        raise NotFound("step_not_found")
    step.instruction = new_instruction.strip()
    step.test_status = "corrected"
    if version.state == "draft":
        from autoskill.services.versioning.state_machine import transition

        await transition(session, version, "testing", actor=None, reason="step corrected during trial")
    changelog = (version.changelog or "").rstrip()
    version.changelog = (
        changelog + "\n" if changelog else ""
    ) + f"- step {step_key}: {note or 'instruction updated during trial'}"
    await rebuild_package(session, version)
    return step
