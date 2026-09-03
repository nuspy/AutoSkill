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


@dataclass
class ProcedureDef:
    kind: str
    steps: list[StepDef]
    max_iterations: int = 200

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
    procedure_id: str, ordinal: int, key: str, kind: str, attempt: int, human_input: dict | None
) -> ProcedureStep:
    return ProcedureStep(
        procedure_id=procedure_id,
        ordinal=ordinal,
        key=key,
        kind=kind,
        status="running",
        attempt=attempt,
        input={"human_input": human_input} if human_input else {},
        started_at=utcnow(),
    )


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

        row = _new_step_row(procedure_id, ordinal, key, step_def.kind, 1, human_input)
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
                row = _new_step_row(procedure_id, ordinal, key, step_def.kind, attempt + 1, human_input)
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
            procedure.context = ctx.state
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
