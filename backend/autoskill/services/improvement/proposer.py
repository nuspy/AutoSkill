"""Turn an analysis into a proposed patch version (draft) with a human-readable rationale."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound
from autoskill.core.events import emit, project_channel
from autoskill.db.base import utcnow
from autoskill.llm.provider import ChatMessage, ChatRequest
from autoskill.llm.registry import get_provider
from autoskill.llm.structured import structured
from autoskill.llm.usage import record_usage
from autoskill.models.improvement import ImprovementProposal
from autoskill.models.project import ProjectMember
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.models.trial import Run
from autoskill.prompts import render
from autoskill.services.drafting.author import generate_draft
from autoskill.services.improvement.analyzer import collect
from autoskill.services.memory.context import memory_context
from autoskill.services.memory.store import add_entry
from autoskill.services.notifications import notify
from autoskill.services.versioning.changes import compare

LANGUAGE_NAMES = {"en": "English", "it": "Italian", "hu": "Hungarian", "de": "German", "es": "Spanish", "fr": "French"}


class AnalystMemory(BaseModel):
    kind: Literal["lesson_learned", "technical_note"]
    title: str
    body: str
    step_key: str | None = None


class AnalystOutput(BaseModel):
    hypotheses: list[str] = Field(min_length=1, max_length=5)
    instructions: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    memory_entries: list[AnalystMemory] = Field(default_factory=list)


async def create_proposal(
    session: AsyncSession, *, skill_id: str, base_version_id: str, trigger: str, requested_by: str | None
) -> ImprovementProposal:
    skill = await session.get(Skill, skill_id)
    base = await session.get(SkillVersion, base_version_id)
    if skill is None or base is None or base.skill_id != skill_id:
        raise NotFound("version_not_found")
    open_ = (
        await session.execute(
            select(ImprovementProposal).where(
                ImprovementProposal.base_version_id == base_version_id,
                ImprovementProposal.state.in_(("analyzing", "proposed", "under_review")),
            )
        )
    ).scalar_one_or_none()
    if open_ is not None:
        raise Conflict("proposal_already_open", proposal_id=open_.id)
    proposal = ImprovementProposal(
        project_id=skill.project_id,
        skill_id=skill_id,
        base_version_id=base_version_id,
        trigger=trigger,
        requested_by=requested_by,
        state="analyzing",
    )
    session.add(proposal)
    await session.flush()
    return proposal


async def run_proposal(session: AsyncSession, proposal_id: str, *, language: str = "en") -> ImprovementProposal:
    proposal = await session.get(ImprovementProposal, proposal_id)
    if proposal is None:
        raise NotFound("proposal_not_found")
    skill = await session.get(Skill, proposal.skill_id)
    base = await session.get(SkillVersion, proposal.base_version_id)
    assert skill is not None and base is not None
    try:
        analysis = await collect(session, skill.id, base.id)
        proposal.analysis = analysis
        proposal.source_run_ids = analysis["source_run_ids"]
        proposal.source_issue_ids = analysis["source_issue_ids"]
        if not analysis["clusters"]:
            proposal.state = "failed"
            proposal.error = "nothing to improve: no failures, issues or corrections in the window"
            await session.commit()
            return proposal
        provider, provider_id = await get_provider(session, skill.project_id, "analyst")
        prompt = render(
            "improvement_rationale",
            language_name=LANGUAGE_NAMES.get(language, "English"),
            skill_title=skill.title,
            version=base.version,
            analysis=analysis,
            memory=await memory_context(session, skill.id, budget_tokens=1500),
        )
        result = await structured(
            provider,
            ChatRequest(
                messages=[ChatMessage(role="user", content=prompt)], temperature=0.1, max_tokens=3000, purpose="analyst"
            ),
            AnalystOutput,
        )
        await record_usage(session, skill.project_id, provider_id, result.usage)
        out: AnalystOutput = result.value
        proposal.analysis = {**analysis, "hypotheses": out.hypotheses}
        proposal.rationale = out.rationale
        await session.commit()
        version = await generate_draft(
            session,
            skill_id=skill.id,
            user_id=None,
            mode="patch",
            base_version_id=base.id,
            origin="improvement",
            language=language,
            instructions="Improve the skill based on real-use problems.\n\nHypotheses:\n- "
            + "\n- ".join(out.hypotheses)
            + "\n\nInstructions:\n"
            + out.instructions,
        )
        version.rationale = out.rationale
        proposal = await session.get(ImprovementProposal, proposal_id)
        proposal.proposed_version_id = version.id
        diff = await compare(session, skill, version, base)
        proposal.diff_summary = {
            "files": [{"path": f["path"], "status": f["status"]} for f in diff["files"]],
            "steps": diff["steps"],
            "suggested_bump": diff["suggested_bump"],
        }
        proposal.golden_pass_rate = await golden_step_coverage(session, base, version)
        for m in out.memory_entries:
            await add_entry(
                session,
                skill.id,
                kind=m.kind,
                title=m.title,
                body=m.body,
                step_key=m.step_key,
                source="improvement",
                source_ref=proposal.id,
                skill_version_id=version.id,
                status="proposed",
            )
        proposal.state = "proposed"
        await session.commit()
        members = (
            (await session.execute(select(ProjectMember).where(ProjectMember.project_id == skill.project_id)))
            .scalars()
            .all()
        )
        for m in members:
            if m.role.value in ("owner", "editor"):
                await notify(
                    session,
                    m.user_id,
                    "proposal_ready",
                    f"Improvement proposed: {skill.title} v{version.version}",
                    body=out.rationale[:500],
                    subject_type="improvement_proposal",
                    subject_id=proposal.id,
                    payload={"skill_id": skill.id, "version_id": version.id},
                )
        await session.commit()
        await emit(
            project_channel(skill.project_id),
            "proposal.ready",
            {"proposal_id": proposal.id, "skill_id": skill.id, "version_id": version.id},
        )
    except Exception as exc:  # noqa: BLE001 - recorded on the proposal
        await session.rollback()
        proposal = await session.get(ImprovementProposal, proposal_id)
        if proposal is not None:
            proposal.state = "failed"
            proposal.error = str(exc)[:2000]
            await session.commit()
        raise
    return proposal


async def golden_step_coverage(session: AsyncSession, base: SkillVersion, proposed: SkillVersion) -> float | None:
    """Share of golden runs whose recorded steps still exist in the proposed version (no execution on the server)."""
    golden = (
        (await session.execute(select(Run).where(Run.skill_version_id == base.id, Run.is_golden.is_(True))))
        .scalars()
        .all()
    )
    if not golden:
        return None
    new_keys = {
        s.key
        for s in (
            await session.execute(select(StepDefinition).where(StepDefinition.skill_version_id == proposed.id))
        ).scalars()
    }
    from autoskill.models.trial import RunStep

    covered = 0
    for run in golden:
        keys = {s.step_key for s in (await session.execute(select(RunStep).where(RunStep.run_id == run.id))).scalars()}
        if keys <= new_keys:
            covered += 1
    return round(covered / len(golden), 3)


async def decide(
    session: AsyncSession, proposal: ImprovementProposal, *, accept: bool, reviewer_id: str, comment: str | None
) -> ImprovementProposal:
    if proposal.state not in ("proposed", "under_review"):
        raise Conflict("proposal_not_open", state=proposal.state)
    from autoskill.models.memory import SkillMemoryEntry

    entries = (
        (
            await session.execute(
                select(SkillMemoryEntry).where(
                    SkillMemoryEntry.source_ref == proposal.id, SkillMemoryEntry.status == "proposed"
                )
            )
        )
        .scalars()
        .all()
    )
    proposal.reviewer_id = reviewer_id
    proposal.decided_at = utcnow()
    proposal.decision_comment = comment
    if accept:
        proposal.state = "accepted"
        for e in entries:
            e.status = "active"
    else:
        proposal.state = "rejected"
        for e in entries:
            e.status = "archived"
        if proposal.proposed_version_id:
            version = await session.get(SkillVersion, proposal.proposed_version_id)
            if version is not None and version.state in ("draft", "testing"):
                from autoskill.services.versioning.state_machine import transition

                await transition(session, version, "discarded", actor=None, reason="improvement proposal rejected")
                skill = await session.get(Skill, proposal.skill_id)
                if skill is not None and skill.latest_version_id == version.id:
                    skill.latest_version_id = version.parent_version_id
    return proposal
