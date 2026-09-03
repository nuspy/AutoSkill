"""Phased checkpoints for step-by-step trials.

Deterministic rules enforced here (the agent can only *ask*; the server decides):
  explain -> preview -> [execute] -> verify, per step and iteration
  * a `preview` needs an accepted `explain` of the same step/iteration
  * an `execute` needs a `continue` on the `preview`; irreversible steps additionally need the human's
    `authorize_execute` decision, which mints the confirmation token the generated tools require
  * a `verify` needs a preview (simulated steps) or an execute (real steps)
  * moving to the next step needs `approve_and_authorize_next` on `verify`
Async mode auto-decides `continue` (and `approve_and_authorize_next`) so the agent never blocks; the
human reviews afterwards.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.events import emit, project_channel, user_channel
from autoskill.db.base import utcnow
from autoskill.models.skill_version import StepDefinition
from autoskill.models.trial import CHECKPOINT_PHASES, DECISIONS, Checkpoint, Run, TrialSession
from autoskill.services.runs.redaction import cap_payload, redact
from autoskill.services.settings import get_setting

PHASE_ORDER = {p: i for i, p in enumerate(CHECKPOINT_PHASES)}
ALLOWED_DECISIONS = {
    "explain": {"continue", "change", "skip", "stop"},
    "preview": {"continue", "change", "redo", "skip", "stop", "authorize_execute"},
    "execute": {"continue", "change", "stop"},
    "verify": {"approve_and_authorize_next", "change", "redo", "stop"},
}


async def _step_definition(session: AsyncSession, version_id: str, step_key: str) -> StepDefinition | None:
    res = await session.execute(
        select(StepDefinition).where(StepDefinition.skill_version_id == version_id, StepDefinition.key == step_key)
    )
    return res.scalar_one_or_none()


async def _last_checkpoint(
    session: AsyncSession, run_id: str, step_key: str, iteration: int, phase: str
) -> Checkpoint | None:
    res = await session.execute(
        select(Checkpoint)
        .where(
            Checkpoint.run_id == run_id,
            Checkpoint.step_key == step_key,
            Checkpoint.iteration == iteration,
            Checkpoint.phase == phase,
        )
        .order_by(Checkpoint.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


def _execution_mode(step: StepDefinition | None, trial: TrialSession | None, requested: str | None) -> str:
    if trial is None:
        return requested or "real"
    if step is None:
        return "simulated"
    return {"real": "real", "simulate": "simulated", "sandbox_copy": "sandbox_copy"}.get(step.trial_mode, "simulated")


async def create_checkpoint(
    session: AsyncSession,
    *,
    run: Run,
    trial: TrialSession | None,
    step_key: str,
    phase: str,
    proposal: dict[str, Any],
    iteration: int | None = None,
    requested_mode: str | None = None,
) -> Checkpoint:
    if phase not in CHECKPOINT_PHASES:
        raise ValidationFailed("unknown_phase", phases=list(CHECKPOINT_PHASES))
    if run.status != "running":
        raise Conflict("run_not_running", status=run.status)
    step = await _step_definition(session, run.skill_version_id, step_key) if run.skill_version_id else None
    if trial is not None and step is None:
        raise ValidationFailed("unknown_step", step_key=step_key)
    it = iteration or (trial.current_iteration if trial and trial.current_step_key == step_key else 1)
    mode = _execution_mode(step, trial, requested_mode)

    # ---- ordering rules -------------------------------------------------------------
    if phase == "preview":
        prev = await _last_checkpoint(session, run.id, step_key, it, "explain")
        if prev is None or prev.decision not in ("continue",):
            raise Conflict("explain_required", message="Send an accepted 'explain' checkpoint before 'preview'.")
    elif phase == "execute":
        prev = await _last_checkpoint(session, run.id, step_key, it, "preview")
        if prev is None or prev.decision not in ("continue", "authorize_execute"):
            raise Conflict("preview_required", message="An accepted 'preview' is required before 'execute'.")
        if mode == "simulated":
            raise Conflict(
                "simulated_step",
                message="This step is simulated in trials: describe the effect in 'preview' and go to 'verify'.",
            )
        if step is not None and step.requires_explicit_auth and prev.decision != "authorize_execute":
            raise Conflict(
                "explicit_authorization_required",
                message="Irreversible step: the person must authorize execution from the preview.",
            )
    elif phase == "verify":
        prev = await _last_checkpoint(session, run.id, step_key, it, "execute")
        if prev is None or prev.decision != "continue":
            prev = await _last_checkpoint(session, run.id, step_key, it, "preview")
            if prev is None or prev.decision not in ("continue", "authorize_execute"):
                raise Conflict("preview_required", message="'verify' needs an accepted 'preview' or 'execute'.")
    elif phase == "explain" and trial is not None:
        # explain of a new step requires the previous step to be authorized (unless first / redo)
        if trial.current_step_key and trial.current_step_key != step_key:
            last_verify = await _last_checkpoint(
                session, run.id, trial.current_step_key, trial.current_iteration, "verify"
            )
            if last_verify is None or last_verify.decision not in ("approve_and_authorize_next",):
                if not await _skipped(session, run.id, trial.current_step_key, trial.current_iteration):
                    raise Conflict(
                        "previous_step_not_authorized",
                        message=f"Step {trial.current_step_key!r} was not approved; finish it or ask to skip it.",
                    )
        if trial.current_step_key != step_key:
            trial.current_step_key = step_key
            trial.current_iteration = 1
            it = 1

    timeout = int(await get_setting(session, "checkpoint_timeout_minutes") or 120)
    cp = Checkpoint(
        run_id=run.id,
        trial_session_id=trial.id if trial else None,
        step_key=step_key,
        phase=phase,
        iteration=it,
        execution_mode=mode,
        proposal=cap_payload(redact(proposal)),
        expires_at=utcnow() + timedelta(minutes=timeout),
        created_at=utcnow(),
    )
    session.add(cp)
    await session.flush()
    if trial is None or trial.mode == "async":
        auto = "approve_and_authorize_next" if phase == "verify" else "continue"
        if phase == "preview" and step is not None and step.requires_explicit_auth:
            auto = "continue"  # never auto-authorize an irreversible execute
        cp.state = "decided"
        cp.decision = auto
        cp.decided_by = None
        cp.decided_at = utcnow()
        if auto == "approve_and_authorize_next" and trial is not None and step is not None:
            _apply_approval(step, trial, step_key)
    else:
        payload = {
            "checkpoint_id": cp.id,
            "run_id": run.id,
            "trial_session_id": trial.id,
            "step_key": step_key,
            "phase": phase,
            "iteration": it,
        }
        await emit(user_channel(trial.user_id), "checkpoint.waiting", payload)
        await emit(project_channel(run.project_id), "checkpoint.waiting", payload)
    return cp


def _apply_approval(step: StepDefinition, trial: TrialSession, step_key: str) -> None:
    step.test_status = "corrected" if any(c["step_key"] == step_key for c in trial.corrections) else "confirmed"
    step.confirmations_count += 1


async def _skipped(session: AsyncSession, run_id: str, step_key: str, iteration: int) -> bool:
    res = await session.execute(
        select(Checkpoint).where(
            Checkpoint.run_id == run_id,
            Checkpoint.step_key == step_key,
            Checkpoint.iteration == iteration,
            Checkpoint.decision == "skip",
        )
    )
    return res.scalars().first() is not None


async def decide(
    session: AsyncSession,
    cp: Checkpoint,
    *,
    decision: str,
    user_id: str | None,
    correction_text: str | None = None,
    updated_instructions: str | None = None,
) -> Checkpoint:
    if cp.state != "pending":
        raise Conflict("checkpoint_already_decided", decision=cp.decision)
    if decision not in DECISIONS or decision not in ALLOWED_DECISIONS[cp.phase]:
        raise ValidationFailed("decision_not_allowed", phase=cp.phase, allowed=sorted(ALLOWED_DECISIONS[cp.phase]))
    if cp.expires_at < utcnow():
        cp.state = "expired"
        raise Conflict("checkpoint_expired")
    cp.state = "decided"
    cp.decision = decision
    cp.correction_text = correction_text
    cp.updated_instructions = updated_instructions
    cp.decided_by = user_id
    cp.decided_at = utcnow()
    if decision == "authorize_execute":
        cp.confirmation_token = secrets.token_urlsafe(24)
    trial = await session.get(TrialSession, cp.trial_session_id) if cp.trial_session_id else None
    run = await session.get(Run, cp.run_id)
    if trial is not None:
        if decision in ("change", "redo"):
            trial.current_iteration = cp.iteration + 1
            if correction_text:
                trial.corrections = [
                    *trial.corrections,
                    {
                        "step_key": cp.step_key,
                        "iteration": cp.iteration,
                        "text": correction_text,
                        "at": utcnow().isoformat(),
                    },
                ]
        if decision == "approve_and_authorize_next" and run and run.skill_version_id:
            step = await _step_definition(session, run.skill_version_id, cp.step_key)
            if step is not None:
                step.test_status = (
                    "corrected" if any(c["step_key"] == cp.step_key for c in trial.corrections) else "confirmed"
                )
                step.confirmations_count += 1
        if decision == "stop" and run is not None and run.status == "running":
            run.status = "aborted"
            run.ended_at = utcnow()
    await emit(
        project_channel(run.project_id) if run else "none",
        "checkpoint.decided",
        {"checkpoint_id": cp.id, "decision": decision, "step_key": cp.step_key},
    )
    return cp


async def wait_for_decision(session_factory, checkpoint_id: str, timeout_s: int) -> Checkpoint:
    """Long-poll helper: re-reads the checkpoint until decided or timeout (capped at 50 s)."""
    deadline = asyncio.get_event_loop().time() + max(0, min(timeout_s, 50))
    while True:
        async with session_factory() as session:
            cp = await session.get(Checkpoint, checkpoint_id)
            if cp is None:
                raise NotFound("checkpoint_not_found")
            if cp.state == "pending" and cp.expires_at < utcnow():
                cp.state = "expired"
                await session.commit()
            if cp.state != "pending" or asyncio.get_event_loop().time() >= deadline:
                session.expunge(cp)
                return cp
        await asyncio.sleep(0.5)


def decision_payload(cp: Checkpoint) -> dict[str, Any]:
    if cp.state == "pending":
        return {"status": "pending", "checkpoint_id": cp.id}
    return {
        "status": cp.state,
        "checkpoint_id": cp.id,
        "decision": cp.decision,
        "correction_text": cp.correction_text,
        "updated_instructions": cp.updated_instructions,
        "confirmation_token": cp.confirmation_token,
        "iteration": cp.iteration,
    }
