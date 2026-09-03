"""Draft generation: knowledge + memory + library -> DraftSpec (LLM) -> SkillPackage (code) -> SkillVersion."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound
from autoskill.core.events import emit, project_channel, user_channel
from autoskill.db.base import utcnow
from autoskill.llm.provider import ChatMessage, ChatRequest, LlmError
from autoskill.llm.registry import get_provider
from autoskill.llm.structured import structured
from autoskill.llm.usage import record_usage
from autoskill.models.interview import KnowledgeDoc
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillDependency, SkillVersion, StepDefinition
from autoskill.prompts import render
from autoskill.schemas.draft import DraftSpec
from autoskill.services.drafting.assemble import assemble_package, trial_mode_for
from autoskill.services.library.catalog import library_catalog
from autoskill.services.memory.context import memory_context
from autoskill.services.memory.store import list_entries
from autoskill.services.packaging.skill_package import SkillPackage, ValidationReport
from autoskill.services.packaging.store import load_package, store_package
from autoskill.services.versioning.semver import next_version, parse

LANGUAGE_NAMES = {"en": "English", "it": "Italian", "hu": "Hungarian", "de": "German", "es": "Spanish", "fr": "French"}
ALLOWED_PACKAGES = "pandas, openpyxl, httpx, pyyaml, python-dateutil"


async def _latest_frozen_knowledge(session: AsyncSession, skill_id: str) -> KnowledgeDoc:
    res = await session.execute(
        select(KnowledgeDoc)
        .where(KnowledgeDoc.skill_id == skill_id, KnowledgeDoc.frozen.is_(True))
        .order_by(KnowledgeDoc.revision.desc())
        .limit(1)
    )
    knowledge = res.scalar_one_or_none()
    if knowledge is None:
        raise Conflict("knowledge_not_frozen", message="Finish the interview before drafting.")
    return knowledge


def _repair_prompt(report: ValidationReport) -> str:
    return (
        "The generated skill failed validation. Fix these problems and return the full corrected draft:\n"
        + "\n".join(f"- [{i.code}] {i.message}" for i in report.errors)
    )


async def generate_draft(
    session: AsyncSession,
    *,
    skill_id: str,
    user_id: str | None,
    mode: str = "new",
    instructions: str | None = None,
    base_version_id: str | None = None,
    origin: str = "interview",
    language: str = "en",
    progress=None,
) -> SkillVersion:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        raise NotFound("skill_not_found")
    if skill.development_state == "suspended":
        raise Conflict("skill_suspended")
    knowledge = await _latest_frozen_knowledge(session, skill_id)
    memory_text = await memory_context(session, skill_id, budget_tokens=2500)
    memory_ids = [e.id for e in await list_entries(session, skill_id, status="active")]
    library = await library_catalog(session)
    previous: SkillVersion | None = None
    previous_md: str | None = None
    if mode == "patch":
        previous = await session.get(SkillVersion, base_version_id) if base_version_id else None
        if previous is None:
            res = await session.execute(
                select(SkillVersion)
                .where(SkillVersion.skill_id == skill_id, SkillVersion.state != "discarded")
                .order_by(SkillVersion.created_at.desc())
                .limit(1)
            )
            previous = res.scalar_one_or_none()
        if previous is not None:
            previous_md = load_package(skill.name, previous).skill_md

    provider, provider_id = await get_provider(session, skill.project_id, "author")
    system = render(
        "author_system", language_name=LANGUAGE_NAMES.get(language, "English"), allowed_packages=ALLOWED_PACKAGES
    )
    prompt = render(
        "author_draft",
        skill_title=skill.title,
        skill_name=skill.name,
        knowledge_json=json.dumps(knowledge.doc, ensure_ascii=False),
        memory=memory_text,
        library=library,
        instructions=instructions,
        previous_skill_md=previous_md,
    )
    messages = [ChatMessage(role="system", content=system), ChatMessage(role="user", content=prompt)]
    version_str = (
        await next_version(session, skill_id, "patch" if mode == "patch" else "minor")
        if previous
        else await next_version(session, skill_id)
    )
    if progress:
        await progress(20, "writing the skill")

    build_log: list[str] = []
    pkg: SkillPackage | None = None
    spec: DraftSpec | None = None
    report: ValidationReport | None = None
    for attempt in range(2):
        result = await structured(
            provider,
            ChatRequest(messages=messages, temperature=0.2, max_tokens=8000, seed=11, purpose="author"),
            DraftSpec,
        )
        await record_usage(session, skill.project_id, provider_id, result.usage)
        spec = result.value
        known_slugs = {c["slug"] for c in library}
        spec.dependencies = [d for d in spec.dependencies if d.component_slug in known_slugs]
        for step in spec.steps:
            if step.library_component_slug and step.library_component_slug not in known_slugs:
                step.library_component_slug = None
        pkg = assemble_package(
            skill_name=skill.name,
            version=version_str,
            spec=spec,
            language=language,
            metadata={
                "author": "autoskill",
                "autoskill_skill_id": skill.id,
                "autoskill_project": skill.project_id,
                "generated_at": utcnow().isoformat(),
            },
        )
        report = pkg.validate()
        status = "ok" if report.ok else "validation errors"
        build_log.append(f"attempt {attempt + 1}: {status} ({len(report.issues)} issues, strategy={result.strategy})")
        if report.ok:
            break
        messages = messages + [
            ChatMessage(role="assistant", content=json.dumps(spec.model_dump())),
            ChatMessage(role="user", content=_repair_prompt(report)),
        ]
    assert pkg is not None and spec is not None and report is not None
    if not report.ok:
        raise LlmError("draft failed validation: " + "; ".join(i.message for i in report.errors))
    if progress:
        await progress(80, "saving the version")

    major, minor, patch = parse(version_str)
    # a previous un-tested draft of the same skill is superseded by the new draft
    res = await session.execute(
        select(SkillVersion).where(SkillVersion.skill_id == skill_id, SkillVersion.is_current_draft.is_(True))
    )
    for old in res.scalars():
        old.is_current_draft = False
    version = SkillVersion(
        skill_id=skill_id,
        version=version_str,
        major=major,
        minor=minor,
        patch=patch,
        state="draft",
        parent_version_id=previous.id if previous else None,
        origin=origin,
        knowledge_snapshot_id=knowledge.id,
        memory_snapshot=memory_ids,
        changelog=spec.changelog or None,
        validation_report=report.as_dict(),
        build_log="\n".join(build_log),
        draft_spec=spec.model_dump(),
        build=1,
        created_by=user_id or "system",
        state_changed_at=utcnow(),
        is_current_draft=True,
    )
    session.add(version)
    await session.flush()
    store_package(version, pkg)
    for i, step in enumerate(spec.steps, 1):
        session.add(
            StepDefinition(
                skill_version_id=version.id,
                ordinal=i,
                key=step.key,
                title=step.title,
                instruction=step.instruction,
                kind=step.kind,
                side_effects=step.side_effects,
                restore_strategy=step.restore_strategy,
                trial_mode=trial_mode_for(step),
                requires_explicit_auth=step.side_effects == "irreversible",
                inputs=step.inputs,
                outputs=step.outputs,
                data_source_refs=step.data_source_refs,
                success_criteria=step.success_criteria or None,
                failure_modes=step.failure_modes,
                network=step.network,
                library_component_slug=step.library_component_slug,
            )
        )
    for dep in spec.dependencies:
        session.add(SkillDependency(skill_version_id=version.id, component_slug=dep.component_slug, reason=dep.reason))
    skill.latest_version_id = version.id
    if spec.description and not skill.summary:
        skill.summary = spec.description[:2000]
    await session.commit()
    payload: dict[str, Any] = {"skill_id": skill_id, "version_id": version.id, "version": version_str}
    await emit(project_channel(skill.project_id), "version.created", payload)
    if user_id:
        await emit(user_channel(user_id), "version.created", payload)
    return version
