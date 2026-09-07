"""An interview must never ask the same question for ever.

Seen in a real session: a document listed a data source ("the backup copy of the chosen file") for
which every confirmed edge case had been written with an empty `source_ref`. G5 counts an edge case
against a source only when `source_ref` names it, so the gate stayed red; the supervisor kept aiming
at G5; the interviewer kept rephrasing the same question about the backup copy; the person kept
answering it. Six turns, no progress, and on that trajectory the session ends at the turn budget in
`blocked` — having asked twenty questions to learn nothing.

The person could not have escaped it by answering better, which is what makes it code's problem.
After `MAX_GATE_ATTEMPTS` tries code stops aiming at that gate and lets the interview reach its
summary, where what stayed unsettled can at least be said out loud.
"""

from __future__ import annotations

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from autoskill.schemas.knowledge import SourceRef
from autoskill.services.interview.gates import compute_gates
from autoskill.services.procedures.defs.interview import MAX_GATE_ATTEMPTS
from tests.conftest import auth, register
from tests.test_gates_engine import complete_doc


def doc_that_never_satisfies_g5() -> dict:
    """A second data source that no confirmed edge case names — exactly the real shape.

    Every edge case is confirmed, so the person has plainly answered; they are simply all attached to
    the first source. G5 has an escape hatch for a document with a single source, which is why this
    needs two: the real session had four.
    """
    doc = complete_doc()
    doc.human_confirmed = False
    doc.data_sources.append(
        SourceRef(
            ref="backup-copy",
            kind="spreadsheet",
            role="output",
            access="same folder as the original",
            fields_used=["number", "amount"],
        )
    )
    for edge in doc.edge_cases:
        edge.confirmed = True
        edge.source_ref = "invoices"
    return doc.model_dump()


def test_the_document_really_is_stuck_on_g5() -> None:
    """Guards the premise: without this the test below could pass for the wrong reason."""
    from autoskill.schemas.knowledge import KnowledgeDocModel

    gates = {g.id: g for g in compute_gates(KnowledgeDocModel.model_validate(doc_that_never_satisfies_g5()))}
    assert gates["G5"].passed is False
    assert "backup-copy" in gates["G5"].detail


async def test_a_gate_that_will_not_close_is_set_aside_instead_of_looping(app_client):
    user, headers, project = await setup(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        stuck = doc_that_never_satisfies_g5()
        supervisor_wants_g5 = Scripted(
            purpose="supervisor",
            json={
                "decision": "need_more",
                "reasons": ["no confirmed edge case for the source"],
                "missing": ["edge case"],
                "target_gate": "G5",
                "next_question": "What happens when the file cannot be read?",
                "confidence": 0.9,
            },
        )
        question = Scripted(
            purpose="interviewer",
            json={
                "question": "What should happen if the invoices sheet cannot be opened?",
                "why": "to settle the edge case",
                "expects": "text",
                "options": [],
                "target_gate": "G5",
            },
        )
        # intake, then as many (supervisor -> question -> ingest) rounds as the loop could ever want
        script = [Scripted(purpose="interviewer", json=stuck)]
        for _ in range(MAX_GATE_ATTEMPTS + 3):
            script += [supervisor_wants_g5, question, Scripted(purpose="interviewer", json=stuck)]
        # once code gives up on G5 nothing fails any more, so the run ends in a summary
        script += [supervisor_wants_g5, Scripted(purpose="interviewer", text="Summary of the task.")]
        fake.script(*script)

        created = await app_client.post(
            f"/api/v1/projects/{project['id']}/interviews",
            json={"title": "Invoices", "description": "check invoices", "language": "en"},
            headers=headers,
        )
        session_id = created.json()["id"]
        await get_job_runner().wait_all()

        seen_gates: list[str] = []
        for _ in range(MAX_GATE_ATTEMPTS + 3):
            detail = (await app_client.get(f"/api/v1/interviews/{session_id}", headers=headers)).json()
            if detail["session"]["state"] != "awaiting_answer":
                break
            seen_gates.append((detail["session"]["pending_question"] or {}).get("target_gate"))
            await app_client.post(
                f"/api/v1/interviews/{session_id}/answer", json={"text": "It should stop."}, headers=headers
            )
            await get_job_runner().wait_all()

        detail = (await app_client.get(f"/api/v1/interviews/{session_id}", headers=headers)).json()
        assert seen_gates.count("G5") <= MAX_GATE_ATTEMPTS, f"G5 was asked {seen_gates.count('G5')} times"
        assert detail["session"]["state"] != "awaiting_answer", "the interview is still stuck on the same gate"
        assert detail["supervisor"]["exhausted_gates"] == ["G5"], "the gate given up on must be recorded, not hidden"
    finally:
        set_fake_provider(None)


async def setup(app_client):
    user = await register(app_client, "alice@example.com")
    headers = auth(user["access_token"])
    project = (await app_client.post("/api/v1/projects", json={"name": "Ops"}, headers=headers)).json()
    return user, headers, project
