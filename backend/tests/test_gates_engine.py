import pytest

from autoskill.schemas.knowledge import (
    AcceptanceCriterion,
    EdgeCase,
    Integration,
    KnowledgeDocModel,
    SourceRef,
    Step,
    TaskInfo,
)
from autoskill.services.interview.gates import all_passed, compute_gates, first_failing


def complete_doc() -> KnowledgeDocModel:
    return KnowledgeDocModel(
        task=TaskInfo(
            name="Invoice check", goal="Verify supplier invoices", trigger="every Monday", actor_role="clerk"
        ),
        data_sources=[
            SourceRef(
                ref="invoices",
                kind="spreadsheet",
                role="input",
                access="shared drive /Invoices",
                fields_used=["number", "amount"],
            )
        ],
        steps=[
            Step(
                key="open",
                title="Open sheet",
                description="Open the invoices sheet",
                kind_hint="deterministic",
                uses=["invoices"],
                example="open Invoices.xlsx",
                side_effects="read_only",
                restore_strategy="none",
            ),
            Step(
                key="flag",
                title="Flag anomalies",
                description="Flag rows over budget",
                kind_hint="generative",
                uses=["invoices"],
                decision_rules=["amount > 1000 => flag"],
                example="row 12 flagged",
                side_effects="reversible",
                restore_strategy="backup_file",
            ),
        ],
        edge_cases=[
            EdgeCase(
                condition="empty sheet", expected_handling="stop and notify", source_ref="invoices", confirmed=True
            )
        ],
        acceptance_criteria=[
            AcceptanceCriterion(id="A1", statement="all rows over 1000 are flagged", checkable_by="human")
        ],
        integrations=[
            Integration(system="email", purpose="notify", protocol="SMTP", credentials_needed=["SMTP_PASSWORD"])
        ],
        human_confirmed=True,
    )


def test_complete_doc_passes_all_gates():
    gates = compute_gates(complete_doc())
    assert all_passed(gates), [g.model_dump() for g in gates if not g.passed]
    assert len(gates) == 10


@pytest.mark.parametrize(
    "mutate, failing",
    [
        (lambda d: d.task.__setattr__("trigger", ""), "G1"),
        (lambda d: d.steps[0].uses.append("unknown"), "G2"),
        (lambda d: d.steps.pop(), "G3"),
        (lambda d: d.steps[1].__setattr__("decision_rules", []), "G4"),
        (lambda d: d.edge_cases.clear(), "G5"),
        (lambda d: d.acceptance_criteria.clear(), "G6"),
        (lambda d: d.open_questions.append("what?"), "G7"),
        (lambda d: d.integrations[0].__setattr__("credentials_needed", []), "G9"),
        (lambda d: d.steps[1].__setattr__("restore_strategy", "unknown"), "G10"),
    ],
)
def test_each_gate_detects_its_problem(mutate, failing):
    doc = complete_doc()
    mutate(doc)
    gates = compute_gates(doc)
    assert first_failing(gates).id == failing


def test_g8_is_skipped_by_first_failing_but_not_all_passed():
    doc = complete_doc()
    doc.human_confirmed = False
    gates = compute_gates(doc)
    assert first_failing(gates) is None
    assert not all_passed(gates)
    assert all_passed(gates, skip=("G8",))


# --- procedure engine -------------------------------------------------------------------

from sqlalchemy import select  # noqa: E402

from autoskill.db.session import get_session_factory  # noqa: E402
from autoskill.models.procedure import Procedure, ProcedureStep  # noqa: E402
from autoskill.services.procedures.engine import (  # noqa: E402
    Done,
    Next,
    ProcedureDef,
    StepDef,
    Wait,
    create_procedure,
    register,
    resume,
    run,
)

calls: list[str] = []


async def step_a(ctx):
    calls.append("a")
    ctx.state["count"] = ctx.state.get("count", 0) + 1
    return Next()


async def step_wait(ctx):
    calls.append("wait")
    if ctx.human_input is None:
        return Wait("approval", output={"asked": True})
    ctx.state["approved"] = ctx.human_input.get("approve")
    return Next("loop" if not ctx.state["approved"] else "finish")


async def step_loop(ctx):
    calls.append("loop")
    return Next("a")


async def step_finish(ctx):
    calls.append("finish")
    return Done({"count": ctx.state.get("count", 0)})


async def flaky(ctx):
    calls.append("flaky")
    ctx.state["tries"] = ctx.state.get("tries", 0) + 1
    if len([c for c in calls if c == "flaky"]) < 2:
        raise RuntimeError("boom")
    return Next()


async def always_fails(ctx):
    raise RuntimeError("nope")


register(
    ProcedureDef(
        kind="test_proc",
        steps=[
            StepDef("a", "code", step_a),
            StepDef("wait", "human_auth", step_wait),
            StepDef("loop", "code", step_loop),
            StepDef("finish", "code", step_finish),
        ],
        max_iterations=20,
    )
)
register(
    ProcedureDef(
        kind="test_flaky",
        steps=[StepDef("flaky", "code", flaky, max_attempts=3), StepDef("finish", "code", step_finish)],
    )
)
register(ProcedureDef(kind="test_fail", steps=[StepDef("bad", "code", always_fails, max_attempts=2)]))
register(
    ProcedureDef(
        kind="test_infinite", steps=[StepDef("a", "code", step_a), StepDef("loop", "code", step_loop)], max_iterations=5
    )
)


async def test_engine_waits_resumes_loops_and_completes(app_client):
    calls.clear()
    async with get_session_factory()() as session:
        proc = await create_procedure(session, "test_proc", subject_type="t", subject_id="1", project_id=None)
        await session.commit()
        proc = await run(session, proc)
        assert proc.state == "waiting_human" and proc.waiting_for == "approval"
        assert calls == ["a", "wait"]
        await resume(session, proc, {"approve": False})
        proc = await run(session, proc)
        assert proc.state == "waiting_human"
        assert calls == ["a", "wait", "wait", "loop", "a", "wait"]
        await resume(session, proc, {"approve": True})
        proc = await run(session, proc)
        assert proc.state == "completed"
        assert proc.context["count"] == 2
        steps = (
            (
                await session.execute(
                    select(ProcedureStep).where(ProcedureStep.procedure_id == proc.id).order_by(ProcedureStep.ordinal)
                )
            )
            .scalars()
            .all()
        )
        assert [s.key for s in steps] == ["a", "wait", "wait", "loop", "a", "wait", "wait", "finish"]
        assert steps[-1].output == {"count": 2}


async def test_engine_retries_then_fails_and_bounds_iterations(app_client):
    calls.clear()
    async with get_session_factory()() as session:
        proc = await create_procedure(session, "test_flaky", subject_type="t", subject_id="2", project_id=None)
        await session.commit()
        proc = await run(session, proc)
        assert proc.state == "completed"
        steps = (
            (await session.execute(select(ProcedureStep).where(ProcedureStep.procedure_id == proc.id))).scalars().all()
        )
        assert steps[0].attempt == 2 and steps[0].status == "succeeded"

        bad = await create_procedure(session, "test_fail", subject_type="t", subject_id="3", project_id=None)
        await session.commit()
        bad = await run(session, bad)
        assert bad.state == "failed" and "nope" in bad.error

        inf = await create_procedure(session, "test_infinite", subject_type="t", subject_id="4", project_id=None)
        await session.commit()
        inf = await run(session, inf)
        assert inf.state == "failed" and "max iterations" in inf.error
        assert (await session.get(Procedure, inf.id)).iteration == 5
