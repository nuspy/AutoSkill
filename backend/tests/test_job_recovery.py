"""A restart must not silently lose the work that was in flight.

The inline runner keeps its tasks in memory, so a reload after an edit, a deploy or a laptop going to
sleep used to strand whatever was running: the `jobs` row said `running` for ever, and the interview
it was driving waited for a worker that no longer existed while the person in the browser watched a
spinner. These tests pin the recovery and, just as importantly, its limits.
"""

from __future__ import annotations

from httpx import AsyncClient

from autoskill.core.jobs import InlineJobRunner, JobContext, get_job_runner, job
from autoskill.db.base import utcnow
from autoskill.db.session import get_session_factory
from autoskill.models.job import Job
from autoskill.models.procedure import Procedure, ProcedureStep
from autoskill.services.procedures import engine

ran: list[str] = []


@job("test.recoverable")
async def _recoverable(ctx: JobContext, marker: str = "", **_) -> dict:
    ran.append(marker)
    return {"marker": marker}


async def _add_job(status: str, marker: str) -> str:
    async with get_session_factory()() as session:
        row = Job(type="test.recoverable", payload={"marker": marker}, status=status)
        session.add(row)
        await session.commit()
        return row.id


async def test_a_running_job_is_run_again_after_a_restart(app_client: AsyncClient) -> None:
    ran.clear()
    job_id = await _add_job("running", "in-flight")

    runner = get_job_runner()
    assert isinstance(runner, InlineJobRunner)
    assert await runner.recover() == 1
    await runner.wait_all()

    assert ran == ["in-flight"]
    async with get_session_factory()() as session:
        row = await session.get(Job, job_id)
        assert row is not None and row.status == "succeeded"


async def test_a_queued_job_is_dispatched_too(app_client: AsyncClient) -> None:
    """A job enqueued a moment before the process died never reached a task at all."""
    ran.clear()
    await _add_job("queued", "never-started")

    runner = get_job_runner()
    assert await runner.recover() == 1
    await runner.wait_all()
    assert ran == ["never-started"]


async def test_finished_jobs_are_left_alone(app_client: AsyncClient) -> None:
    """Recovery must not re-run history: only `queued` and `running` were owned by the dead process."""
    ran.clear()
    await _add_job("succeeded", "done")
    await _add_job("failed", "broken")

    runner = get_job_runner()
    assert await runner.recover() == 0
    await runner.wait_all()
    assert ran == []


async def test_interrupted_steps_are_closed_and_the_procedure_stays_resumable(app_client: AsyncClient) -> None:
    """The step is honest about being cut short; the procedure keeps its place so the job can resume."""
    async with get_session_factory()() as session:
        procedure = Procedure(kind="interview", subject_type="interview", state="running", current_step_key="ask")
        session.add(procedure)
        await session.commit()
        step = ProcedureStep(
            procedure_id=procedure.id, ordinal=1, key="ask", kind="llm", status="running", started_at=utcnow()
        )
        session.add(step)
        await session.commit()
        step_id, procedure_id = step.id, procedure.id

    async with get_session_factory()() as session:
        assert await engine.mark_interrupted(session) == 1

    async with get_session_factory()() as session:
        step = await session.get(ProcedureStep, step_id)
        assert step is not None
        assert step.status == "failed"
        assert "restart" in (step.error or "")
        assert step.ended_at is not None
        procedure = await session.get(Procedure, procedure_id)
        assert procedure is not None
        assert procedure.state == "running", "the procedure must stay resumable from current_step_key"
        assert procedure.current_step_key == "ask"
