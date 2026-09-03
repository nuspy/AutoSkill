from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.api.v1.skills import get_skill_for
from autoskill.core.errors import NotFound
from autoskill.core.jobs import get_job_runner
from autoskill.models.improvement import ImprovementProposal
from autoskill.models.project import ProjectRole
from autoskill.schemas.common import ORMModel
from autoskill.services.improvement.analyzer import collect
from autoskill.services.improvement.proposer import create_proposal, decide

router = APIRouter(tags=["improvements"])


class ProposalOut(ORMModel):
    id: str
    project_id: str
    skill_id: str
    base_version_id: str
    proposed_version_id: str | None
    state: str
    trigger: str
    source_run_ids: list
    source_issue_ids: list
    analysis: dict
    rationale: str | None
    diff_summary: dict
    golden_pass_rate: float | None
    requested_by: str | None
    reviewer_id: str | None
    decision_comment: str | None
    error: str | None
    created_at: object
    updated_at: object


class ProposeIn(BaseModel):
    base_version_id: str


class ProposalDecision(BaseModel):
    accept: bool
    comment: str | None = Field(default=None, max_length=4000)


@router.get("/skills/{skill_id}/improvements", response_model=list[ProposalOut])
async def list_proposals(skill_id: str, session: SessionDep, user: CurrentUser):
    await get_skill_for(session, skill_id, user, ProjectRole.viewer)
    res = await session.execute(
        select(ImprovementProposal)
        .where(ImprovementProposal.skill_id == skill_id)
        .order_by(ImprovementProposal.created_at.desc())
    )
    return res.scalars().all()


@router.get("/skills/{skill_id}/improvements/analysis")
async def analysis(skill_id: str, session: SessionDep, user: CurrentUser, version_id: str) -> dict:
    await get_skill_for(session, skill_id, user, ProjectRole.viewer)
    return await collect(session, skill_id, version_id)


@router.post("/skills/{skill_id}/improvements", response_model=ProposalOut, status_code=202)
async def propose(skill_id: str, body: ProposeIn, session: SessionDep, user: CurrentUser):
    skill = await get_skill_for(session, skill_id, user, ProjectRole.editor)
    proposal = await create_proposal(
        session, skill_id=skill_id, base_version_id=body.base_version_id, trigger="manual", requested_by=user.id
    )
    await session.commit()
    await session.refresh(proposal)
    await get_job_runner().enqueue(
        "improvement.propose",
        {"proposal_id": proposal.id, "language": user.locale},
        project_id=skill.project_id,
        user_id=user.id,
    )
    return proposal


@router.get("/improvements/{proposal_id}", response_model=ProposalOut)
async def detail(proposal_id: str, session: SessionDep, user: CurrentUser):
    proposal = await session.get(ImprovementProposal, proposal_id)
    if proposal is None:
        raise NotFound("proposal_not_found")
    await get_skill_for(session, proposal.skill_id, user, ProjectRole.viewer)
    if proposal.state == "proposed":
        proposal.state = "under_review"
        await session.commit()
    return proposal


@router.post("/improvements/{proposal_id}/decision", response_model=ProposalOut)
async def decision(proposal_id: str, body: ProposalDecision, session: SessionDep, user: CurrentUser):
    proposal = await session.get(ImprovementProposal, proposal_id)
    if proposal is None:
        raise NotFound("proposal_not_found")
    await get_skill_for(session, proposal.skill_id, user, ProjectRole.editor)
    await decide(session, proposal, accept=body.accept, reviewer_id=user.id, comment=body.comment)
    await session.commit()
    await session.refresh(proposal)
    return proposal
