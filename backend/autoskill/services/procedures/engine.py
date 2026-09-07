"""Deterministic, resumable procedure engine.

A procedure definition is an ordered mapping of step keys to `StepDef`s. Each handler receives a
`ProcedureContext` and returns one of:

* `Next(key)`   continue with that step (or the following one when key is None)
* `Wait(what)`  pause until a human provides `what` (state = waiting_human)
* `Done(result)` finish the procedure

Every executed step is persisted in `procedure_steps`, so the engine can be re-entered after a crash
or after a human input: `run()` always resumes from `procedures.current_step_key`. Loops are bounded by
`max_iterations`; a handler exception is retried `max_attempts` times before the procedure fails.
Handler kinds are descriptive ("code", "llm", "supervisor", "human_auth") and recorded with each step.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.db.base import utcnow
from autoskill.models.procedure import Procedure, ProcedureStep

log = logging.getLogger(__name__)


@dataclass
class Next:
    key: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] | None = None
    usage: dict[str, int] | None = None


@dataclass
class Wait:
    waiting_for: str
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class Done:
    result: dict[str, Any] = field(default_factory=dict)


StepOutcome = Next | Wait | Done


@dataclass
class ProcedureContext:
    session: AsyncSession
    procedure: Procedure
    state: dict[str, Any]  # mutable, persisted as procedure.context
    human_input: dict[str, Any] | None = None  # set when resuming after a Wait


Handler = Callable[[ProcedureContext], Awaitable[StepOutcome]]


@dataclass
class StepDef:
    key: str
    kind: str
    handler: Handler
    max_attempts: int = 2


# Snapshot/restore of the state a procedure owns outside `procedure.context` (for the interview:
# the session row, its knowledge revision and how far the transcript had got). The engine stays
# generic: each definition declares what belongs to its own state.
Snapshot = Callable[[AsyncSession, Procedure], Awaitable[dict[str, Any]]]
Restore = Callable[[AsyncSession, Procedure, dict[str, Any]], Awaitable[None]]


@dataclass
class ProcedureDef:
    kind: str
    steps: list[StepDef]
    max_iterations: int = 200
    snapshot: Snapshot | None = None
    restore: Restore | None = None

    def index(self, key: str) -> int:
        for i, s in enumerate(self.steps):
            if s.key == key:
                return i
        raise KeyError(key)

    def after(self, key: str) -> str | None:
        i = self.index(key)
        return self.steps[i + 1].key if i + 1 < len(self.steps) else None


_definitions: dict[str, ProcedureDef] = {}


def register(definition: ProcedureDef) -> ProcedureDef:
    _definitions[definition.kind] = definition
    return definition


def get_definition(kind: str) -> ProcedureDef:
    return _definitions[kind]


async def create_procedure(
    session: AsyncSession,
    kind: str,
    *,
    subject_type: str | None,
    subject_id: str | None,
    project_id: str | None,
    context: dict[str, Any] | None = None,
) -> Procedure:
    definition = get_definition(kind)
    row = Procedure(
        kind=kind,
        subject_type=subject_type,
        subject_id=subject_id,
        project_id=project_id,
        state="running",
        current_step_key=definition.steps[0].key,
        context=context or {},
    )
    session.add(row)
    await session.flush()
    return row


def _new_step_row(
    procedure_id: str,
    ordinal: int,
    key: str,
    kind: str,
    attempt: int,
    human_input: dict | None,
    checkpoint: dict | None = None,
) -> ProcedureStep:
    return ProcedureStep(
        procedure_id=procedure_id,
        ordinal=ordinal,
        key=key,
        kind=kind,
        status="running",
        attempt=attempt,
        checkpoint=checkpoint,
        input={"human_input": human_input} if human_input else {},
        started_at=utcnow(),
    )


async def capture(session: AsyncSession, procedure: Procedure) -> dict[str, Any]:
    """State to come back to: the procedure's own fields plus whatever the definition owns."""
    definition = get_definition(procedure.kind)
    snap: dict[str, Any] = {
        "procedure": {
            "context": dict(procedure.context),
            "current_step_key": procedure.current_step_key,
            "iteration": procedure.iteration,
            "state": procedure.state,
            "waiting_for": procedure.waiting_for,
        }
    }
    if definition.snapshot is not None:
        snap["subject"] = await definition.snapshot(session, procedure)
    return snap


async def restore_snapshot(session: AsyncSession, procedure: Procedure, snap: dict[str, Any]) -> None:
    """Put the procedure back as `snap` describes it. The caller decides the resulting state."""
    definition = get_definition(procedure.kind)
    fields = snap.get("procedure") or {}
    procedure.context = dict(fields.get("context") or {})
    procedure.current_step_key = fields.get("current_step_key")
    procedure.iteration = int(fields.get("iteration") or 0)
    procedure.waiting_for = fields.get("waiting_for")
    if definition.restore is not None and "subject" in snap:
        await definition.restore(session, procedure, snap["subject"])


async def _next_ordinal(session: AsyncSession, procedure_id: str) -> int:
    res = await session.execute(
        select(func.coalesce(func.max(ProcedureStep.ordinal), 0)).where(ProcedureStep.procedure_id == procedure_id)
    )
    return int(res.scalar_one()) + 1


async def resume(session: AsyncSession, procedure: Procedure, human_input: dict[str, Any]) -> None:
    """Provide the awaited human input; the caller then calls `run`."""
    if procedure.state != "waiting_human":
        raise RuntimeError(f"procedure {procedure.id} is not waiting for input (state={procedure.state})")
    ctx = dict(procedure.context)
    ctx["_human_input"] = human_input
    ctx["_waiting_for"] = procedure.waiting_for
    procedure.context = ctx
    procedure.state = "running"
    procedure.waiting_for = None


async def run(session: AsyncSession, procedure: Procedure) -> Procedure:
    """Execute steps until the procedure waits, completes or fails. Commits after every step."""
    definition = get_definition(procedure.kind)
    while procedure.state == "running":
        if procedure.iteration >= definition.max_iterations:
            procedure.state = "failed"
            procedure.error = "max iterations reached"
            procedure.finished_at = utcnow()
            await session.commit()
            break
        key = procedure.current_step_key or definition.steps[0].key
        step_def = definition.steps[definition.index(key)]
        state = dict(procedure.context)
        human_input = state.pop("_human_input", None)
        state.pop("_waiting_for", None)
        ctx = ProcedureContext(session=session, procedure=procedure, state=state, human_input=human_input)
        procedure_id = procedure.id
        ordinal = await _next_ordinal(session, procedure_id)
        # taken before the handler runs: this is where a replay of this step rewinds to
        checkpoint = await capture(session, procedure)

        row = _new_step_row(procedure_id, ordinal, key, step_def.kind, 1, human_input, checkpoint)
        session.add(row)
        outcome: StepOutcome | None = None
        error: str | None = None
        errors: list[str] = []
        for attempt in range(1, step_def.max_attempts + 1):
            try:
                outcome = await step_def.handler(ctx)
                error = None
                break
            except Exception as exc:  # noqa: BLE001 - recorded and retried
                errors.append(f"attempt {attempt}: {exc}\n{traceback.format_exc()[-1200:]}")
                error = "\n---\n".join(errors)
                log.warning("procedure %s step %s attempt %s failed: %s", procedure_id, key, attempt, exc)
                # discard partial work of the failed attempt and reload fresh state
                await session.rollback()
                procedure = await session.get(Procedure, procedure_id)  # type: ignore[assignment]
                assert procedure is not None
                next_attempt = attempt + 1 if attempt < step_def.max_attempts else attempt
                row = _new_step_row(
                    procedure_id, ordinal, key, step_def.kind, next_attempt, human_input, checkpoint
                )
                session.add(row)
                ctx = ProcedureContext(session=session, procedure=procedure, state=dict(state), human_input=human_input)
        procedure.iteration += 1
        row.ended_at = utcnow()
        if outcome is None:
            row.status = "failed"
            row.error = error
            procedure.state = "failed"
            procedure.error = error
            procedure.finished_at = utcnow()
            # keep the human input in the context: a retry re-runs this step and needs it back
            failed_state = dict(ctx.state)
            if human_input is not None:
                failed_state["_human_input"] = human_input
            procedure.context = failed_state
            await session.commit()
            break
        procedure.context = ctx.state
        if isinstance(outcome, Next):
            row.status = "succeeded"
            row.output = outcome.output
            row.supervisor_decision = outcome.decision
            row.llm_usage = outcome.usage
            next_key = outcome.key or definition.after(key)
            row.next_key = next_key
            if next_key is None:
                procedure.state = "completed"
                procedure.finished_at = utcnow()
            else:
                procedure.current_step_key = next_key
        elif isinstance(outcome, Wait):
            row.status = "waiting"
            row.output = outcome.output
            procedure.state = "waiting_human"
            procedure.waiting_for = outcome.waiting_for
            # the same step re-runs with the human input when resumed
        else:
            row.status = "succeeded"
            row.output = outcome.result
            procedure.state = "completed"
            procedure.finished_at = utcnow()
        await session.commit()
    return procedure


# --- navigating the past -------------------------------------------------------------------
#
# Steps are never deleted. A replay rewinds to the checkpoint of a past step and runs it again;
# the steps it would replace stay in place until the user decides:
#
#   replay(7) -> stash of "where I was now", rewind to checkpoint of step 7, run again
#       accept  -> the old steps from 7 on become 'superseded', the re-run is the truth
#       discard -> the re-run becomes 'discarded', the stash puts everything back


async def steps(session: AsyncSession, procedure: Procedure) -> list[ProcedureStep]:
    res = await session.execute(
        select(ProcedureStep)
        .where(ProcedureStep.procedure_id == procedure.id)
        .order_by(ProcedureStep.ordinal, ProcedureStep.attempt)
    )
    return list(res.scalars().all())


async def _step_at(session: AsyncSession, procedure: Procedure, ordinal: int) -> ProcedureStep:
    """The last attempt recorded for that ordinal: the one whose checkpoint describes the step."""
    res = await session.execute(
        select(ProcedureStep)
        .where(ProcedureStep.procedure_id == procedure.id, ProcedureStep.ordinal == ordinal)
        .order_by(ProcedureStep.attempt.desc())
    )
    step = res.scalars().first()
    if step is None:
        raise LookupError(f"step {ordinal} not found")
    return step


async def start_replay(session: AsyncSession, procedure: Procedure, ordinal: int) -> ProcedureStep:
    """Rewind to just before step `ordinal` and re-run it, keeping a way back."""
    if procedure.replay:
        raise RuntimeError("a replay is already in progress")
    if procedure.state not in ("running", "waiting_human", "failed", "completed"):
        raise RuntimeError(f"cannot replay a {procedure.state} procedure")
    step = await _step_at(session, procedure, ordinal)
    if step.checkpoint is None:
        raise RuntimeError("this step predates checkpoints and cannot be replayed")
    stash = await capture(session, procedure)
    next_ordinal = await _next_ordinal(session, procedure.id)
    await restore_snapshot(session, procedure, step.checkpoint)
    procedure.replay = {"from_ordinal": ordinal, "new_from_ordinal": next_ordinal, "stash": stash}
    procedure.state = "running"
    procedure.error = None
    procedure.finished_at = None
    await session.commit()
    return step


async def accept_replay(session: AsyncSession, procedure: Procedure) -> None:
    """Keep the re-run: the steps it replaced are marked superseded and stay readable."""
    info = procedure.replay
    if not info:
        raise RuntimeError("no replay in progress")
    old_from, new_from = int(info["from_ordinal"]), int(info["new_from_ordinal"])
    for step in await steps(session, procedure):
        if old_from <= step.ordinal < new_from and step.status not in ("superseded", "discarded"):
            step.status = "superseded"
    procedure.replay = None
    await session.commit()


async def discard_replay(session: AsyncSession, procedure: Procedure) -> None:
    """Throw the re-run away and go back exactly where the replay started."""
    info = procedure.replay
    if not info:
        raise RuntimeError("no replay in progress")
    new_from = int(info["new_from_ordinal"])
    for step in await steps(session, procedure):
        if step.ordinal >= new_from:
            step.status = "discarded"
    stash = info["stash"]
    await restore_snapshot(session, procedure, stash)
    fields = stash.get("procedure") or {}
    procedure.state = fields.get("state") or "running"
    procedure.error = None
    procedure.finished_at = None
    procedure.replay = None
    await session.commit()


async def mark_interrupted(session: AsyncSession) -> int:
    """Close the step rows a dead process left open, and report how many there were.

    A step row is written before its handler runs and updated when the handler returns, so a process
    that stops in the middle of one — a reload, a deploy, a kill — leaves behind a row that claims to
    be running for ever. It misleads twice: in the timeline the person reads, and in the ordinals a
    replay walks back through.

    At startup nothing of ours is running yet, so a row still marked `running` belongs to a process
    that no longer exists. The procedure itself is deliberately left alone: it is still `running`,
    and that is precisely what lets its job resume it from `current_step_key`, writing a fresh
    attempt of the same step rather than pretending the interrupted one succeeded.
    """
    rows = (await session.execute(select(ProcedureStep).where(ProcedureStep.status == "running"))).scalars().all()
    for row in rows:
        row.status = "failed"
        row.error = "interrupted by a server restart"
        row.ended_at = utcnow()
    if rows:
        await session.commit()
    return len(rows)
