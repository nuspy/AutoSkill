"""Navigating the past of an interview: read the steps, re-run one, keep it or throw it away."""

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from tests.test_interview import partial_doc, setup_project


def question(text: str, gate: str = "G2") -> dict:
    return {"question": text, "why": "to know", "expects": "text", "options": [], "target_gate": gate}


def supervisor_needs_more() -> dict:
    return {
        "decision": "need_more",
        "reasons": ["not enough"],
        "missing": ["access"],
        "target_gate": "G2",
        "next_question": None,
        "confidence": 0.8,
    }


async def start_until_first_question(app_client, headers, project, fake, text: str) -> str:
    fake.script(
        Scripted(purpose="interviewer", json=partial_doc()),  # intake
        Scripted(purpose="supervisor", json=supervisor_needs_more()),  # supervise
        Scripted(purpose="interviewer", json=question(text)),  # ask
    )
    created = await app_client.post(
        f"/api/v1/projects/{project['id']}/interviews",
        json={"title": "Invoice check", "description": "Weekly invoice review.", "language": "en"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    await get_job_runner().wait_all()
    return created.json()["id"]


async def test_step_history_is_readable(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        sid = await start_until_first_question(app_client, headers, project, fake, "Where are the invoices?")

        steps = (await app_client.get(f"/api/v1/interviews/{sid}/steps", headers=headers)).json()
        assert [s["key"] for s in steps] == ["intake", "compute_gates", "supervise", "ask"]
        assert [s["status"] for s in steps] == ["succeeded", "succeeded", "succeeded", "waiting"]
        # every step carries what it produced and can be replayed
        assert all(s["replayable"] for s in steps)
        assert steps[2]["supervisor_decision"]["effective"] == "need_more"
        assert steps[3]["output"]["question"]["question"] == "Where are the invoices?"
    finally:
        set_fake_provider(None)


async def test_replay_discarded_restores_the_previous_question(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        sid = await start_until_first_question(app_client, headers, project, fake, "First question?")
        steps = (await app_client.get(f"/api/v1/interviews/{sid}/steps", headers=headers)).json()
        ask_ordinal = next(s["ordinal"] for s in steps if s["key"] == "ask")

        # re-run the step that asked the question, this time the model words it differently
        fake.script(Scripted(purpose="interviewer", json=question("Second question?")))
        replayed = await app_client.post(
            f"/api/v1/interviews/{sid}/steps/{ask_ordinal}/replay", headers=headers
        )
        assert replayed.status_code == 200, replayed.text
        await get_job_runner().wait_all()

        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["pending_question"]["question"] == "Second question?"
        # the first question is no longer part of the conversation
        assert [m["content"] for m in detail["messages"]] == ["Second question?"]
        assert detail["replay"]["from_ordinal"] == ask_ordinal

        # thrown away: everything goes back to how it was
        discarded = await app_client.post(f"/api/v1/interviews/{sid}/replay/discard", headers=headers)
        assert discarded.status_code == 200, discarded.text
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["pending_question"]["question"] == "First question?"
        assert [m["content"] for m in detail["messages"]] == ["First question?"]
        assert detail["replay"] is None

        steps = (await app_client.get(f"/api/v1/interviews/{sid}/steps", headers=headers)).json()
        # the re-run is kept as history, marked as thrown away; the original is untouched
        assert [s["status"] for s in steps if s["ordinal"] > ask_ordinal] == ["discarded"]
        assert next(s["status"] for s in steps if s["ordinal"] == ask_ordinal) == "waiting"

        # and the interview carries on from where it was
        fake.script(
            Scripted(purpose="interviewer", json=partial_doc()),  # ingest
            Scripted(purpose="supervisor", json=supervisor_needs_more()),
            Scripted(purpose="interviewer", json=question("Third question?")),
        )
        answered = await app_client.post(
            f"/api/v1/interviews/{sid}/answer", json={"text": "On the shared drive."}, headers=headers
        )
        assert answered.status_code == 200, answered.text
        await get_job_runner().wait_all()
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert [m["content"] for m in detail["messages"]] == [
            "First question?",
            "On the shared drive.",
            "Third question?",
        ]
    finally:
        set_fake_provider(None)


async def test_replay_accepted_supersedes_the_old_steps(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        sid = await start_until_first_question(app_client, headers, project, fake, "First question?")
        steps = (await app_client.get(f"/api/v1/interviews/{sid}/steps", headers=headers)).json()
        supervise_ordinal = next(s["ordinal"] for s in steps if s["key"] == "supervise")

        # rewind further back: re-run the supervisor, which then asks a new question
        fake.script(
            Scripted(purpose="supervisor", json=supervisor_needs_more()),
            Scripted(purpose="interviewer", json=question("Better question?")),
        )
        replayed = await app_client.post(
            f"/api/v1/interviews/{sid}/steps/{supervise_ordinal}/replay", headers=headers
        )
        assert replayed.status_code == 200, replayed.text
        await get_job_runner().wait_all()

        accepted = await app_client.post(f"/api/v1/interviews/{sid}/replay/accept", headers=headers)
        assert accepted.status_code == 200, accepted.text

        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["pending_question"]["question"] == "Better question?"
        assert [m["content"] for m in detail["messages"]] == ["Better question?"]
        assert detail["replay"] is None

        steps = (await app_client.get(f"/api/v1/interviews/{sid}/steps", headers=headers)).json()
        old = [s for s in steps if s["ordinal"] in (supervise_ordinal, supervise_ordinal + 1)]
        assert [s["status"] for s in old] == ["superseded", "superseded"]
        # nothing was deleted: the replaced steps stay readable
        assert next(s["output"] for s in steps if s["ordinal"] == supervise_ordinal + 1)["question"]["question"] == (
            "First question?"
        )

        # once a replay is settled another one can start, on a superseded step too: going back to
        # an abandoned branch is exactly what "continue from any step" means
        fake.script(Scripted(purpose="interviewer", json=question("Third question?")))
        again = await app_client.post(
            f"/api/v1/interviews/{sid}/steps/{supervise_ordinal + 1}/replay", headers=headers
        )
        assert again.status_code == 200, again.text
        await get_job_runner().wait_all()
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["pending_question"]["question"] == "Third question?"
    finally:
        set_fake_provider(None)
