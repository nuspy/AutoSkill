"""Phased checkpoints for step-by-step trials.

Deterministic rules enforced here (the agent can only *ask*; the server decides):
  explain -> preview -> [execute] -> verify, per step and iteration
  * a `preview` needs an accepted `explain` of the same step/iteration
  * an `execute` needs a `continue` on the `preview`; irreversible steps additionally need the human's
    `authorize_execute` decision, which mints the confirmation token the generated tools require
  * a `verify` needs a preview (simulated steps) or an execute (real steps)
  * moving to the next step needs `approve_and_authorize_next` on `verify`
  * a real `execute` on a step with a restore strategy needs a snapshot (what the agent backed up); the
    person may then decide `restore` on `execute`/`verify`, the agent restores and sends `restore`, and
    `continue` there starts the next iteration from `explain`
  * deterministic steps confirmed N times (setting auto_confirm_after_confirmations) are auto-decided
    when the trial allows it, never for `execute` nor irreversible steps
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
from autoskill.models.trial import CHECKPOINT_PHASES, DECISIONS, Checkpoint, Run, TrialSession, TrialSnapshot
from autoskill.services.runs.redaction import cap_payload, redact
from autoskill.services.settings import get_setting

PHASE_ORDER = {p: i for i, p in enumerate(CHECKPOINT_PHASES)}
ALLOWED_DECISIONS = {
    "explain": {"continue", "change", "skip", "stop"},
    "preview": {"continue", "change", "redo", "skip", "stop", "authorize_execute"},
    "execute": {"continue", "change", "stop", "restore"},
    "verify": {"approve_and_authorize_next", "change", "redo", "stop", "restore"},
    "restore": {"continue", "stop"},
}
RESTORABLE_STRATEGIES = ("backup_file", "sandbox_copy", "db_transaction")


async def snapshot_for(session: AsyncSession, run_id: str, step_key: str, iteration: int) -> TrialSnapshot | None:
    res = await session.execute(
        select(TrialSnapshot)
        .where(TrialSnapshot.run_id == run_id, TrialSnapshot.step_key == step_key, TrialSnapshot.iteration == iteration)
        .order_by(TrialSnapshot.taken_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def record_snapshot(
    session: AsyncSession, *, run: Run, trial: TrialSession | None, step_key: str, items: list[dict], note: str | None
) -> TrialSnapshot:
    if run.status != "running":
        raise Conflict("run_not_running", status=run.status)
    iteration = trial.current_iteration if trial and trial.current_step_key == step_key else 1
    snap = TrialSnapshot(
        run_id=run.id,
        trial_session_id=trial.id if trial else None,
        step_key=step_key,
        iteration=iteration,
        items=cap_payload(redact({"items": items}))["items"],
        note=note,
        taken_at=utcnow(),
    )
    session.add(snap)
    await session.flush()
    return snap


async def _auto_confirmable(
    session: AsyncSession, trial: TrialSession, step: StepDefinition | None, phase: str
) -> bool:
    """Deterministic steps the person already confirmed N times are not re-asked (unless corrections)."""
    if step is None or not trial.auto_confirm or phase == "execute":
        return False
    if step.kind != "deterministic" or step.test_status != "confirmed" or step.requires_explicit_auth:
        return False
    if step.side_effects == "irreversible" or any(c["step_key"] == step.key for c in trial.corrections):
        return False
    needed = int(await get_setting(session, "auto_confirm_after_confirmations") or 0)
    return needed > 0 and step.confirmations_count >= needed


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
    # Every refusal below carries `expected_phase` / `expected_step_key`: the call that would be
    # accepted right now. A bare "no" is a dead end for an agent — the first real trial ended with one.
    # After a step's `explain` was approved the agent named the next step, was refused, and read the
    # refusal as "the protocol is not working here": it did the whole task unwatched and called
    # `end_run`, while the person's page waited for a step that no longer existed. Being told what to
    # send instead turns the same refusal into a correction.
    if phase == "preview":
        prev = await _last_checkpoint(session, run.id, step_key, it, "explain")
        if prev is None or prev.decision not in ("continue",):
            raise Conflict(
                "explain_required",
                message="Send an accepted 'explain' checkpoint before 'preview'.",
                expected_phase="explain",
                expected_step_key=step_key,
            )
    elif phase == "execute":
        prev = await _last_checkpoint(session, run.id, step_key, it, "preview")
        if prev is None or prev.decision not in ("continue", "authorize_execute"):
            raise Conflict(
                "preview_required",
                message="An accepted 'preview' is required before 'execute'.",
                expected_phase="preview",
                expected_step_key=step_key,
            )
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
        if (
            mode in ("real", "sandbox_copy")
            and step is not None
            and step.restore_strategy in RESTORABLE_STRATEGIES
            and await snapshot_for(session, run.id, step_key, it) is None
        ):
            raise Conflict(
                "snapshot_required",
                message="Back up what this step changes (companion tool `snapshot`) before executing it for real.",
            )
    elif phase == "verify":
        prev = await _last_checkpoint(session, run.id, step_key, it, "execute")
        if prev is None or prev.decision != "continue":
            prev = await _last_checkpoint(session, run.id, step_key, it, "preview")
            if prev is None or prev.decision not in ("continue", "authorize_execute"):
                raise Conflict(
                    "preview_required",
                    message="'verify' needs an accepted 'preview' or 'execute'.",
                    expected_phase="preview",
                    expected_step_key=step_key,
                )
    elif phase == "restore":
        ordered = None
        for prev_phase in ("verify", "execute"):
            prev = await _last_checkpoint(session, run.id, step_key, it, prev_phase)
            if prev is not None and prev.decision == "restore":
                ordered = prev
                break
        if ordered is None:
            raise Conflict("restore_not_requested", message="Send 'restore' only after the person decided 'restore'.")
        snap = await snapshot_for(session, run.id, step_key, it)
        if snap is not None:
            snap.restored_at = utcnow()
            snap.restore_result = cap_payload(redact(proposal))
    elif phase == "explain" and trial is not None:
        # explain of a new step requires the previous step to be authorized (unless first / redo)
        if trial.current_step_key and trial.current_step_key != step_key:
            last_verify = await _last_checkpoint(
                session, run.id, trial.current_step_key, trial.current_iteration, "verify"
            )
            if last_verify is None or last_verify.decision not in ("approve_and_authorize_next",):
                if not await _skipped(session, run.id, trial.current_step_key, trial.current_iteration):
                    # Name the phase that is actually missing, not just the step: after an approved
                    # `explain` the agent owes a `preview`, after an approved `preview` a `verify`.
                    done = {
                        p
                        for p in ("explain", "preview", "execute")
                        if (
                            cp := await _last_checkpoint(
                                session, run.id, trial.current_step_key, trial.current_iteration, p
                            )
                        )
                        is not None
                        and cp.decision in ("continue", "authorize_execute")
                    }
                    missing = "verify" if "preview" in done or "execute" in done else "preview"
                    raise Conflict(
                        "previous_step_not_authorized",
                        message=(
                            f"Step {trial.current_step_key!r} is not finished: it ends with a 'verify' "
                            f"decided 'approve_and_authorize_next'. Send phase {missing!r} for "
                            f"{trial.current_step_key!r} and close it, or ask the person to skip it. "
                            "Do not carry on without checkpoints."
                        ),
                        expected_phase=missing,
                        expected_step_key=trial.current_step_key,
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
    auto_confirmed = (
        trial is not None and trial.mode != "async" and await _auto_confirmable(session, trial, step, phase)
    )
    if trial is None or trial.mode == "async" or auto_confirmed:
        auto = "approve_and_authorize_next" if phase == "verify" else "continue"
        if phase == "preview" and step is not None and step.requires_explicit_auth:
            auto = "continue"  # never auto-authorize an irreversible execute
        cp.state = "decided"
        cp.decision = auto
        cp.decided_by = None
        cp.decided_at = utcnow()
        if auto_confirmed:
            cp.proposal = {**cp.proposal, "auto_confirmed": True}
            await emit(
                user_channel(trial.user_id),
                "checkpoint.auto",
                {"checkpoint_id": cp.id, "step_key": step_key, "phase": phase, "decision": auto},
            )
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
    if decision == "restore":
        if cp.execution_mode not in ("real", "sandbox_copy"):
            raise Conflict("nothing_to_restore", message="Only real or sandbox executions can be restored.")
        if await snapshot_for(session, cp.run_id, cp.step_key, cp.iteration) is None:
            raise Conflict("no_snapshot", message="The agent recorded no snapshot for this step.")
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
        if decision in ("change", "redo") or (decision == "continue" and cp.phase == "restore"):
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
    out = {
        "status": cp.state,
        "checkpoint_id": cp.id,
        "decision": cp.decision,
        "correction_text": cp.correction_text,
        "updated_instructions": cp.updated_instructions,
        "confirmation_token": cp.confirmation_token,
        "iteration": cp.iteration,
    }
    if cp.decision == "restore":
        out["restore_hint"] = (
            "Restore what you backed up for this step (companion tool `restore_snapshot`), then send a "
            "checkpoint with phase='restore' describing what was restored."
        )
    if cp.proposal.get("auto_confirmed"):
        out["auto_confirmed"] = True
    return out


async def next_action(session: AsyncSession, cp: Checkpoint) -> dict[str, Any]:
    """The call the agent is expected to make now, named in the reply that just answered it.

    Three consecutive trials ended the same way: the agent sent `explain` for the first step, was
    told `continue`, and then logged the step and ended the run. The document it had loaded described
    the cycle correctly and in plain terms; the reply it was actually reading said only
    `{"status": "decided", "decision": "continue"}` and left the meaning of that word to memory.

    Instructions at a distance lose to instructions in the reply. So the answer to a checkpoint now
    carries the next phase and step, and a sentence saying it — the same medicine already given to the
    409 on the refusal path, applied to the path an agent is actually on when things go right.
    """
    if cp.state == "pending":
        return {
            "next_call": "await_decision",
            "next_hint": f"Nobody has decided yet. Call `await_decision` with checkpoint id {cp.id}.",
        }
    decision = cp.decision
    step = cp.step_key

    def at(phase: str, why: str) -> dict[str, Any]:
        return {
            "next_phase": phase,
            "next_step_key": step,
            "next_hint": f"{why} Send `checkpoint` with phase={phase!r} for step {step!r}.",
        }

    if decision == "stop":
        return {"next_call": "end_run", "next_hint": "The person stopped the run. Call `end_run` now."}
    if decision == "restore":
        return {
            "next_call": "restore_snapshot",
            "next_hint": (
                f"Restore what you backed up for step {step!r} (`restore_snapshot`), then send "
                "`checkpoint` with phase='restore' describing what was put back."
            ),
        }
    if decision in ("change", "redo"):
        return at("explain", "The person asked for a change: read `updated_instructions` and redo this step.")
    if cp.phase == "explain" and decision == "continue":
        return at("preview", "Do the read-only part of this step, then show what you found and what you plan.")
    if cp.phase == "preview" and decision in ("continue", "authorize_execute"):
        if cp.execution_mode == "simulated":
            return at(
                "verify",
                "This step is simulated in a trial: do not perform the effect, report what would happen.",
            )
        return at("execute", "You may carry the step out for real now.")
    if cp.phase in ("execute", "restore") and decision == "continue":
        return at("verify", "Report the actual result against this step's success criteria.")

    # The step is closed: `approve_and_authorize_next` on a verify, or a skip. What opens next is the
    # following step in the skill's own order — the one thing the agent cannot work out from the reply.
    if decision in ("approve_and_authorize_next", "skip"):
        run = await session.get(Run, cp.run_id)
        if run is None or not run.skill_version_id:
            return {"next_call": "end_run", "next_hint": "Call `end_run` when there is nothing left to do."}
        keys = list(
            (
                await session.execute(
                    select(StepDefinition.key)
                    .where(StepDefinition.skill_version_id == run.skill_version_id)
                    .order_by(StepDefinition.ordinal)
                )
            )
            .scalars()
            .all()
        )
        following = keys[keys.index(step) + 1 :] if step in keys else []
        if not following:
            return {
                "next_call": "end_run",
                "next_hint": "That was the last step. Call `log_step` for it, then `end_run`.",
            }
        nxt = following[0]
        return {
            "next_phase": "explain",
            "next_step_key": nxt,
            "steps_left": len(following),
            "next_hint": (
                f"Step {step!r} is closed — call `log_step` for it. {len(following)} step(s) remain: "
                f"send `checkpoint` with phase='explain' for step {nxt!r}. Do not call `end_run` yet."
            ),
        }
    return {}


async def decision_reply(session: AsyncSession, cp: Checkpoint) -> dict[str, Any]:
    """`decision_payload` plus what to do next — the shape every checkpoint answer returns."""
    return {**decision_payload(cp), **await next_action(session, cp)}


async def agent_progress(session: AsyncSession, trial: TrialSession) -> dict[str, Any]:
    """Where the agent stands in this trial and what it should do next — for the local driver.

    An agent's own loop can end after a single checkpoint (it did `explain`, was told `continue`, and
    stopped instead of moving to `preview`), and then the person's page waits for a step that is never
    coming. The companion polls this to decide, without guessing, whether to nudge the agent on or to
    leave it be:

    * `waiting_on_human` — the last checkpoint is still `pending`. The agent is right to wait; nudging
      it would only make it raise the same checkpoint twice. The driver waits too.
    * `next_hint` set — the last checkpoint is `decided` and the agent has not acted on the decision.
      This is the case to nudge: the hint is the very sentence `await_decision` already returned.
    * `run_open` false — the run ended (`end_run`) or never started. Nothing to drive.

    `last_checkpoint_id` lets the driver tell a nudge that worked (a new checkpoint appeared) from one
    that did nothing, so it can give up instead of prodding a genuinely stuck agent for ever.
    """
    run = (
        await session.execute(
            select(Run).where(Run.trial_session_id == trial.id).order_by(Run.started_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    base = {"run_id": None, "run_status": None, "run_open": False, "started": run is not None,
            "waiting_on_human": False, "next_call": None, "next_hint": None, "next_phase": None,
            "next_step_key": None, "last_checkpoint_id": None}
    if run is None:
        return {**base, "next_call": "start_run",
                "next_hint": "No run has started for this trial. Call `start_run`, then send the first "
                             "`explain` checkpoint for the first step."}
    base.update(run_id=run.id, run_status=run.status)
    if run.ended_at is not None or run.status != "running":
        return base  # the run is closed; there is nothing to drive
    base["run_open"] = True
    cp = (
        await session.execute(
            select(Checkpoint).where(Checkpoint.run_id == run.id).order_by(Checkpoint.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if cp is None:
        return {**base, "next_call": "checkpoint", "next_phase": "explain",
                "next_hint": "The run has started but no checkpoint has been sent yet. Send the first "
                             "`explain` checkpoint for the first step."}
    base["last_checkpoint_id"] = cp.id
    if cp.state == "pending":
        return {**base, "waiting_on_human": True}
    return {**base, **await next_action(session, cp)}
