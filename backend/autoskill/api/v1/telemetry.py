"""Telemetry and companion endpoints: runs, steps, issues, checkpoints (long-poll), step guidance.

Authentication: a project API key (telemetry:write), a user API key from `autoskill login`, or a trial
session token passed as `X-AutoSkill-Trial` (issued when the trial was requested).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep, get_api_key, require_scope
from autoskill.core.errors import Forbidden, NotFound, Unauthorized
from autoskill.db.session import get_session_factory
from autoskill.models.api_key import SCOPE_TELEMETRY_WRITE, SCOPE_TRIAL_CLIENT, ApiKey
from autoskill.models.skill import Skill
from autoskill.models.skill_version import StepDefinition
from autoskill.models.trial import Checkpoint, Run, TrialSession
from autoskill.schemas.common import OkResponse
from autoskill.schemas.trial import (
    CheckpointIn,
    CheckpointOut,
    DecisionIn,
    DiscussionMessageIn,
    DiscussionOut,
    IssueIn,
    RunEnd,
    RunStart,
    RunStartOut,
    StepLog,
)
from autoskill.services.memory.store import list_entries
from autoskill.services.runs import ingestion
from autoskill.services.tester import checkpoints as cps
from autoskill.services.tester import coach
from autoskill.services.trials import service as trials

router = APIRouter(tags=["telemetry"])


class Caller:
    def __init__(self, *, api_key: ApiKey | None = None, trial: TrialSession | None = None) -> None:
        self.api_key = api_key
        self.trial = trial

    @property
    def project_id(self) -> str | None:
        if self.trial:
            return self.trial.project_id
        return self.api_key.project_id if self.api_key else None

    @property
    def user_id(self) -> str | None:
        if self.trial:
            return self.trial.user_id
        return self.api_key.user_id if self.api_key else None


async def get_caller(
    request: Request, session: SessionDep, x_autoskill_trial: Annotated[str | None, Header()] = None
) -> Caller:
    trial = None
    if x_autoskill_trial:
        trial = await trials.trial_from_token(session, x_autoskill_trial)
    auth = request.headers.get("authorization") or request.headers.get("x-api-key")
    if auth:
        key = await get_api_key(request, session)
        if SCOPE_TELEMETRY_WRITE not in key.scopes and SCOPE_TRIAL_CLIENT not in key.scopes:
            require_scope(key, SCOPE_TELEMETRY_WRITE)
        return Caller(api_key=key, trial=trial)
    if trial is not None:
        return Caller(trial=trial)
    raise Unauthorized("api_key_required")


CallerDep = Annotated[Caller, Depends(get_caller)]


async def _run_for(session, caller: Caller, run_id: str) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFound("run_not_found")
    if caller.project_id and run.project_id != caller.project_id and not (caller.api_key and caller.api_key.user_id):
        raise Forbidden("run_forbidden")
    return run


@router.post("/telemetry/runs", response_model=RunStartOut)
async def start_run(body: RunStart, session: SessionDep, caller: CallerDep):
    trial = caller.trial
    if body.trial_session_token and trial is None:
        trial = await trials.trial_from_token(session, body.trial_session_token)
    if trial is not None:
        skill = await session.get(Skill, trial.skill_id)
        version = await session.get(
            __import__("autoskill.models.skill_version", fromlist=["SkillVersion"]).SkillVersion, trial.skill_version_id
        )
    else:
        skill = await ingestion.resolve_skill(
            session, project_id=caller.project_id, skill_name=body.skill_name, skill_id=body.skill_id
        )
        version = await ingestion.resolve_version(session, skill, body.skill_version, body.skill_version_id)
    run = await ingestion.start_run(
        session,
        skill=skill,
        version=version,
        source="trial" if trial else "production",
        trial=trial,
        agent_target=body.agent_target,
        device_id=caller.api_key.device_id if caller.api_key else None,
        user_id=caller.user_id,
        api_key_id=caller.api_key.id if caller.api_key else None,
        inputs_summary=body.inputs_summary,
    )
    await session.commit()
    return RunStartOut(
        run_id=run.id,
        trial_session_id=trial.id if trial else None,
        mode=trial.mode if trial else "production",
        skill_version=run.skill_version,
    )


@router.post("/telemetry/runs/{run_id}/steps", response_model=OkResponse)
async def log_step(
    run_id: str,
    body: StepLog,
    session: SessionDep,
    caller: CallerDep,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    run = await _run_for(session, caller, run_id)
    await ingestion.log_step(session, run, body.model_dump(), idempotency_key=idempotency_key)
    await session.commit()
    return OkResponse()


@router.post("/telemetry/runs/{run_id}/end", response_model=OkResponse)
async def end_run(run_id: str, body: RunEnd, session: SessionDep, caller: CallerDep):
    run = await _run_for(session, caller, run_id)
    await ingestion.end_run(
        session, run, status=body.status, summary=body.summary, error=body.error, llm_usage=body.llm_usage
    )
    await session.commit()
    return OkResponse()


@router.post("/telemetry/issues", response_model=OkResponse)
async def issue(body: IssueIn, session: SessionDep, caller: CallerDep):
    run = await _run_for(session, caller, body.run_id) if body.run_id else None
    if run is not None:
        skill = await session.get(Skill, run.skill_id)
    elif caller.trial is not None:
        skill = await session.get(Skill, caller.trial.skill_id)
    else:
        skill = await ingestion.resolve_skill(
            session, project_id=caller.project_id, skill_name=body.skill_name, skill_id=body.skill_id
        )
    await ingestion.report_issue(
        session,
        skill=skill,
        run=run,
        step_key=body.step_key,
        severity=body.severity,
        description=body.description,
        evidence=body.evidence,
        user_id=caller.user_id,
    )
    await session.commit()
    return OkResponse()


@router.get("/telemetry/guidance/{skill_id}/{step_key}")
async def step_guidance(skill_id: str, step_key: str, session: SessionDep, caller: CallerDep) -> dict:
    """Recent corrections and memory for a step (companion `get_step_guidance`)."""
    skill = await session.get(Skill, skill_id)
    if skill is None:
        raise NotFound("skill_not_found")
    entries = await list_entries(session, skill_id, status="active", step_key=step_key)
    corrections: list[dict] = []
    if caller.trial is not None:
        corrections = [c for c in caller.trial.corrections if c["step_key"] == step_key]
    step = None
    if caller.trial is not None:
        res = await session.execute(
            select(StepDefinition).where(
                StepDefinition.skill_version_id == caller.trial.skill_version_id, StepDefinition.key == step_key
            )
        )
        step = res.scalar_one_or_none()
    return {
        "step_key": step_key,
        "instruction": step.instruction if step else None,
        "trial_mode": step.trial_mode if step else None,
        "requires_explicit_auth": step.requires_explicit_auth if step else None,
        "corrections": corrections,
        "memory": [{"kind": e.kind, "title": e.title, "body": e.body} for e in entries],
    }


# --- checkpoints ----------------------------------------------------------------------


@router.post("/checkpoints")
async def create_checkpoint(body: CheckpointIn, session: SessionDep, caller: CallerDep) -> dict:
    run = await _run_for(session, caller, body.run_id)
    trial = caller.trial
    if trial is None and run.trial_session_id:
        trial = await session.get(TrialSession, run.trial_session_id)
    cp = await cps.create_checkpoint(
        session,
        run=run,
        trial=trial,
        step_key=body.step_key,
        phase=body.phase,
        proposal=body.proposal,
        iteration=body.iteration,
        requested_mode=body.execution_mode,
    )
    await session.commit()
    return cps.decision_payload(cp)


@router.get("/checkpoints/{checkpoint_id}")
async def await_decision(checkpoint_id: str, caller: CallerDep, wait: int = 0) -> dict:
    cp = await cps.wait_for_decision(get_session_factory(), checkpoint_id, wait)
    return cps.decision_payload(cp)


@router.get("/checkpoints/{checkpoint_id}/detail", response_model=CheckpointOut)
async def checkpoint_detail(checkpoint_id: str, session: SessionDep, user: CurrentUser):
    cp = await session.get(Checkpoint, checkpoint_id)
    if cp is None:
        raise NotFound("checkpoint_not_found")
    return cp


@router.post("/checkpoints/{checkpoint_id}/decision", response_model=CheckpointOut)
async def decide(checkpoint_id: str, body: DecisionIn, session: SessionDep, user: CurrentUser):
    cp = await session.get(Checkpoint, checkpoint_id)
    if cp is None:
        raise NotFound("checkpoint_not_found")
    trial = await session.get(TrialSession, cp.trial_session_id) if cp.trial_session_id else None
    if trial is not None and trial.user_id != user.id and user.role.value != "admin":
        raise Forbidden("not_your_trial")
    await cps.decide(
        session,
        cp,
        decision=body.decision,
        user_id=user.id,
        correction_text=body.correction_text,
        updated_instructions=body.updated_instructions,
    )
    await session.commit()
    await session.refresh(cp)
    return cp


# --- discussions ----------------------------------------------------------------------


@router.post("/checkpoints/{checkpoint_id}/discussion", response_model=DiscussionOut)
async def discuss(checkpoint_id: str, body: DiscussionMessageIn, session: SessionDep, user: CurrentUser):
    cp = await session.get(Checkpoint, checkpoint_id)
    if cp is None:
        raise NotFound("checkpoint_not_found")
    run = await session.get(Run, cp.run_id)
    trial = await session.get(TrialSession, cp.trial_session_id) if cp.trial_session_id else None
    skill = await session.get(Skill, run.skill_id)
    disc = await coach.open_discussion(
        session,
        skill=skill,
        version_id=run.skill_version_id,
        step_key=cp.step_key,
        user_id=user.id,
        trial=trial,
        checkpoint=cp,
    )
    await coach.coach_turn(session, disc, body.message, language=user.locale)
    await session.commit()
    await session.refresh(disc)
    return disc


@router.get("/discussions/{discussion_id}", response_model=DiscussionOut)
async def discussion(discussion_id: str, session: SessionDep, user: CurrentUser):
    disc = await session.get(
        __import__("autoskill.models.trial", fromlist=["StepDiscussion"]).StepDiscussion, discussion_id
    )
    if disc is None:
        raise NotFound("discussion_not_found")
    return disc


@router.post("/discussions/{discussion_id}/apply", response_model=DiscussionOut)
async def apply_discussion(discussion_id: str, session: SessionDep, user: CurrentUser):
    """Accept the coach's latest proposal: patch the step, rebuild the package, store memory."""
    from autoskill.models.trial import StepDiscussion

    disc = await session.get(StepDiscussion, discussion_id)
    if disc is None:
        raise NotFound("discussion_not_found")
    proposal = next(
        (m.get("proposal") for m in reversed(disc.messages) if m.get("role") == "assistant" and m.get("proposal")), None
    )
    if proposal is None:
        raise NotFound("no_proposal")
    outcome = coach.CoachOutcome(reply="", **proposal)
    await coach.apply_outcome(session, disc, outcome, user.id)
    # the pending checkpoint (if any) gets a 'change' decision carrying the new instruction
    if disc.checkpoint_id:
        cp = await session.get(Checkpoint, disc.checkpoint_id)
        if cp is not None and cp.state == "pending":
            await cps.decide(
                session,
                cp,
                decision="change",
                user_id=user.id,
                correction_text=outcome.change_summary,
                updated_instructions=outcome.new_instruction,
            )
    await session.commit()
    await session.refresh(disc)
    return disc
