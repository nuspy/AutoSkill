from sqlalchemy import select

from autoskill.core.jobs import JobContext, job
from autoskill.db.session import get_session_factory
from autoskill.models.improvement import ImprovementProposal
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion
from autoskill.services.improvement.analyzer import collect, should_trigger
from autoskill.services.improvement.proposer import create_proposal, run_proposal


@job("improvement.propose")
async def improvement_propose(ctx: JobContext, proposal_id: str, language: str = "en", **_) -> dict:
    async with get_session_factory()() as session:
        proposal = await run_proposal(session, proposal_id, language=language)
        return {"proposal_id": proposal.id, "state": proposal.state, "version_id": proposal.proposed_version_id}


@job("improvement.scan")
async def improvement_scan(ctx: JobContext, **_) -> dict:
    """Cron: look at published/tested versions with enough failures or issues and open proposals."""
    from autoskill.core.jobs import get_job_runner

    opened: list[str] = []
    async with get_session_factory()() as session:
        versions = (
            (await session.execute(select(SkillVersion).where(SkillVersion.state.in_(("published", "tested")))))
            .scalars()
            .all()
        )
        for version in versions:
            skill = await session.get(Skill, version.skill_id)
            if skill is None or skill.development_state != "active":
                continue
            existing = (
                await session.execute(
                    select(ImprovementProposal).where(
                        ImprovementProposal.base_version_id == version.id,
                        ImprovementProposal.state.in_(("analyzing", "proposed", "under_review")),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            analysis = await collect(session, skill.id, version.id)
            trigger = should_trigger(analysis)
            if trigger is None:
                continue
            proposal = await create_proposal(
                session, skill_id=skill.id, base_version_id=version.id, trigger=trigger, requested_by=None
            )
            await session.commit()
            opened.append(proposal.id)
    for pid in opened:
        await get_job_runner().enqueue("improvement.propose", {"proposal_id": pid})
    return {"opened": opened}
