from fastapi import APIRouter, Query
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.api.v1.skills import get_skill_for
from autoskill.core.errors import NotFound
from autoskill.core.permissions import require_project_role
from autoskill.models.project import ProjectRole
from autoskill.models.trial import Checkpoint, Run, RunAnnotation, RunStep
from autoskill.schemas.trial import CheckpointOut, RunDetail, RunFeedback, RunOut, RunStepOut

router = APIRouter(tags=["runs"])


@router.get("/projects/{project_id}/runs", response_model=list[RunOut])
async def list_runs(
    project_id: str,
    session: SessionDep,
    user: CurrentUser,
    skill_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    await require_project_role(session, project_id, user, ProjectRole.viewer)
    stmt = select(Run).where(Run.project_id == project_id)
    if skill_id:
        stmt = stmt.where(Run.skill_id == skill_id)
    if status:
        stmt = stmt.where(Run.status == status)
    res = await session.execute(stmt.order_by(Run.started_at.desc()).limit(limit))
    return res.scalars().all()


@router.get("/runs/{run_id}", response_model=RunDetail)
async def run_detail(run_id: str, session: SessionDep, user: CurrentUser):
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFound("run_not_found")
    await require_project_role(session, run.project_id, user, ProjectRole.viewer)
    steps = (
        (await session.execute(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.ordinal)))
        .scalars()
        .all()
    )
    cps = (
        (await session.execute(select(Checkpoint).where(Checkpoint.run_id == run.id).order_by(Checkpoint.created_at)))
        .scalars()
        .all()
    )
    notes = (
        (
            await session.execute(
                select(RunAnnotation).where(RunAnnotation.run_id == run.id).order_by(RunAnnotation.created_at)
            )
        )
        .scalars()
        .all()
    )
    return RunDetail(
        run=RunOut.model_validate(run),
        steps=[RunStepOut.model_validate(s) for s in steps],
        checkpoints=[CheckpointOut.model_validate(c) for c in cps],
        annotations=[
            {
                "id": n.id,
                "kind": n.kind,
                "severity": n.severity,
                "text": n.text,
                "step_key": n.step_key,
                "created_at": n.created_at.isoformat(),
            }
            for n in notes
        ],
    )


@router.patch("/runs/{run_id}", response_model=RunOut)
async def run_feedback(run_id: str, body: RunFeedback, session: SessionDep, user: CurrentUser):
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFound("run_not_found")
    await get_skill_for(session, run.skill_id, user, ProjectRole.editor)
    if body.human_feedback is not None:
        run.human_feedback = body.human_feedback
    if body.is_golden is not None:
        run.is_golden = body.is_golden
    await session.commit()
    await session.refresh(run)
    return run
