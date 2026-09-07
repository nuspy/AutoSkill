"""The interview stops being blind: an agent attached to the session answers what can be observed.

The application still leads and the person still answers in the browser. What changes is that a
question about the machine can be addressed to the agent, which looks and reports.
"""

import io

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from tests.conftest import auth, register
from tests.test_interview import filled_doc, partial_doc, setup_project


def question(text: str, **extra) -> dict:
    return {"question": text, "why": "to know", "expects": "text", "options": [], "target_gate": "G2", **extra}


def task_question(text: str, targets: list[str]) -> dict:
    """What the model emits when it decides the machine can answer better than the person."""
    return question(
        text,
        audience="agent",
        task={
            "mode": "inspect",
            "kind": "describe_tabular",
            "targets": targets,
            "wants": ["sheet names", "column headers"],
            "may_upload": True,
        },
    )


def supervisor(decision: str = "need_more") -> dict:
    return {
        "decision": decision,
        "reasons": ["not enough"],
        "missing": ["fields"],
        "target_gate": "G2",
        "next_question": None,
        "confidence": 0.8,
    }


def xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Invoices"
    sheet.append(["Supplier", "Amount", "Paid"])
    sheet.append(["Acme", 100, "yes"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


async def start_session(app_client, headers, project, fake, first_question: dict) -> str:
    fake.script(
        Scripted(purpose="interviewer", json=partial_doc()),
        Scripted(purpose="supervisor", json=supervisor()),
        Scripted(purpose="interviewer", json=first_question),
    )
    created = await app_client.post(
        f"/api/v1/projects/{project['id']}/interviews",
        json={"title": "Invoice check", "description": "Weekly invoice review.", "language": "en"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    await get_job_runner().wait_all()
    return created.json()["id"]


async def device_key(app_client, headers) -> str:
    """The key a real agent holds: minted by `autoskill login`, so it carries a user."""
    start = (await app_client.post(
        "/api/v1/auth/device",
        json={"device_name": "workstation", "device_os": "windows", "agent_targets": ["claude_code"]},
    )).json()
    confirmed = await app_client.post(
        "/api/v1/auth/device/confirm", json={"user_code": start["user_code"]}, headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    approved = (await app_client.post(
        "/api/v1/auth/device/token", json={"device_code": start["device_code"]}
    )).json()
    assert approved["status"] == "approved", approved
    return approved["api_key"]


async def agent_key(app_client, headers, project) -> str:
    res = await app_client.post(
        f"/api/v1/projects/{project['id']}/api-keys",
        json={"name": "the machine", "scopes": ["telemetry:write"]},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["key"]


def agent_headers(key: str, token: str) -> dict:
    return {"Authorization": f"Bearer {key}", "X-AutoSkill-Interview": token}


async def test_without_an_agent_nothing_changes(app_client):
    """The contract that matters most: a session with no executor behaves exactly as before."""
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        # the model asks for the agent, but nobody is attached: code sends the question to the person
        sid = await start_session(app_client, headers, project, fake, task_question("Look at ~/Invoices", ["~/Invoices"]))
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["waiting_for"] == "answer"
        assert detail["session"]["pending_question"]["audience"] == "person"
        assert detail["session"]["pending_question"].get("task") is None
    finally:
        set_fake_provider(None)


async def test_the_agent_answers_what_it_can_observe(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        sid = await start_session(app_client, headers, project, fake, question("Which folder holds them?"))

        # the person hands the session to their agent
        handoff = await app_client.post(f"/api/v1/interviews/{sid}/handoff", headers=headers)
        assert handoff.status_code == 200, handoff.text
        token = handoff.json()["session_token"]
        assert "assist_interview" in handoff.json()["instruction"]
        key = await agent_key(app_client, headers, project)
        ah = agent_headers(key, token)

        # the agent takes the turn: it is a question for the person, and it says so
        turn = (await app_client.get("/api/v1/interviews/turn?wait=0", headers=ah)).json()
        assert turn["status"] == "question" and turn["for"] == "person"

        # the person answers in the browser; now the model asks the machine instead
        fake.script(
            Scripted(purpose="interviewer", json=partial_doc()),
            Scripted(purpose="supervisor", json=supervisor()),
            Scripted(purpose="interviewer", json=task_question("Open the newest workbook there.", ["~/Invoices"])),
        )
        answered = await app_client.post(
            f"/api/v1/interviews/{sid}/answer", json={"text": "In ~/Invoices"}, headers=headers
        )
        assert answered.status_code == 200
        await get_job_runner().wait_all()

        turn = (await app_client.get("/api/v1/interviews/turn?wait=0", headers=ah)).json()
        assert turn["status"] == "task" and turn["for"] == "agent"
        assert turn["mode"] == "inspect" and turn["may_upload"] is True
        assert turn["targets"] == ["~/Invoices"]

        # the agent looks, uploads what it found, and reports
        upload = await app_client.post(
            "/api/v1/interviews/turn/attachments",
            files={"file": ("invoices.xlsx", xlsx_bytes(), "application/vnd.ms-excel")},
            headers=ah,
        )
        assert upload.status_code == 201, upload.text
        descriptor = upload.json()
        assert "sheet 'Invoices'" in descriptor["preview"]
        assert "Supplier | Amount | Paid" in descriptor["preview"]

        fake.script(
            Scripted(purpose="interviewer", json=filled_doc()),
            Scripted(purpose="interviewer", text="Here is what I understood."),
        )
        reported = await app_client.post(
            "/api/v1/interviews/turn",
            json={"text": "invoices.xlsx: sheet Invoices, columns Supplier, Amount, Paid",
                  "attachments": [descriptor], "turn_id": turn["turn_id"]},
            headers=ah,
        )
        assert reported.status_code == 200, reported.text
        await get_job_runner().wait_all()

        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        # what the agent reported is in the transcript, and the gates moved on
        assert any("Supplier" in m["content"] for m in detail["messages"])
        assert detail["knowledge"]["completeness"]["passed"] >= 4
        # an inspection is not a question: it does not spend the person's turn budget
        assert detail["session"]["turn_count"] == 1
    finally:
        set_fake_provider(None)


async def test_a_stale_turn_is_refused_with_the_current_one(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        sid = await start_session(app_client, headers, project, fake, question("Which folder?"))
        token = (await app_client.post(f"/api/v1/interviews/{sid}/handoff", headers=headers)).json()["session_token"]
        ah = agent_headers(await agent_key(app_client, headers, project), token)
        turn = (await app_client.get("/api/v1/interviews/turn?wait=0", headers=ah)).json()

        # the person answers from the browser first
        fake.script(
            Scripted(purpose="interviewer", json=partial_doc()),
            Scripted(purpose="supervisor", json=supervisor()),
            Scripted(purpose="interviewer", json=question("And which columns?")),
        )
        await app_client.post(f"/api/v1/interviews/{sid}/answer", json={"text": "~/Invoices"}, headers=headers)
        await get_job_runner().wait_all()

        late = await app_client.post(
            "/api/v1/interviews/turn", json={"text": "too late", "turn_id": turn["turn_id"]}, headers=ah
        )
        assert late.status_code == 409
        body = late.json()["error"]
        assert body["code"] == "turn_superseded"
        # and it hands back what to do instead, rather than a bare refusal
        assert body["details"]["current"]["status"] in ("question", "task")
    finally:
        set_fake_provider(None)


async def test_the_token_opens_one_interview_and_no_other(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        first = await start_session(app_client, headers, project, fake, question("A?"))
        second = await start_session(app_client, headers, project, fake, question("B?"))
        token_a = (await app_client.post(f"/api/v1/interviews/{first}/handoff", headers=headers)).json()["session_token"]
        key = await agent_key(app_client, headers, project)

        res = await app_client.get("/api/v1/interviews/turn?wait=0", headers=agent_headers(key, token_a))
        assert res.status_code == 200, res.text
        turn = res.json()
        assert turn["status"] in ("question", "working")

        # a key without the session token gets nowhere
        bare = await app_client.get("/api/v1/interviews/turn?wait=0", headers={"Authorization": f"Bearer {key}"})
        assert bare.status_code == 401

        # and the browser endpoints still refuse an api key, as they always did
        forbidden = await app_client.get(f"/api/v1/interviews/{second}", headers={"Authorization": f"Bearer {key}"})
        assert forbidden.status_code == 401
    finally:
        set_fake_provider(None)


async def test_a_session_can_be_opened_from_the_agent(app_client):
    """The third door: same interview, opened from the machine, continued in the browser."""
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        # opening an interview writes who owns the skill, so it needs a key that carries a user
        key = await device_key(app_client, headers)
        fake.script(
            Scripted(purpose="interviewer", json=partial_doc()),
            Scripted(purpose="supervisor", json=supervisor()),
            Scripted(purpose="interviewer", json=question("Which folder?")),
        )
        started = await app_client.post(
            "/api/v1/interviews/agent",
            json={"description": "Every Monday I check supplier invoices.", "project": project["slug"]},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert started.status_code == 201, started.text
        body = started.json()
        # the person is sent to the browser, and this machine is already the executor
        assert body["url"].endswith(f"/interview/{body['session_id']}")
        assert body["session_token"]
        await get_job_runner().wait_all()

        turn = (await app_client.get(
            "/api/v1/interviews/turn?wait=0", headers=agent_headers(key, body["session_token"])
        )).json()
        assert turn["status"] in ("question", "working")

        detail = (await app_client.get(f"/api/v1/interviews/{body['session_id']}", headers=headers)).json()
        assert detail["session"]["origin"] == "agent"
        assert detail["session"]["agent_attached"] is True

        # with several projects and none named, it hands back the choice instead of guessing
        await app_client.post("/api/v1/projects", json={"name": "Another"}, headers=headers)
        ambiguous = await app_client.post(
            "/api/v1/interviews/agent",
            json={"description": "Something else"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert ambiguous.status_code == 422
        assert ambiguous.json()["error"]["code"] == "choose_project"
        assert len(ambiguous.json()["error"]["details"]["projects"]) == 2
    finally:
        set_fake_provider(None)


async def test_an_outdated_executor_is_sent_to_update_first(app_client, monkeypatch):
    """The turn is not consumed: after updating and reloading, the agent lands where it left off."""
    from autoskill.schemas.bundle import CompanionEntry
    from autoskill.services.interview import service as interview_service

    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        sid = await start_session(app_client, headers, project, fake, question("Which folder?"))
        token = (await app_client.post(f"/api/v1/interviews/{sid}/handoff", headers=headers)).json()["session_token"]
        ah = agent_headers(await agent_key(app_client, headers, project), token)

        monkeypatch.setattr(
            "autoskill.services.distribution.bundle.companion_entry",
            lambda: CompanionEntry(version="0.9.0", install_command="pipx install --force http://server/x.whl"),
        )

        old = (await app_client.get(
            "/api/v1/interviews/turn?wait=0", headers={**ah, "X-AutoSkill-Client": "0.2.0"}
        )).json()
        assert old["status"] == "update"
        assert "pipx install --force" in old["command"]
        assert "reload" in old["then"].lower()

        # a current executor gets the real turn, and the old one finds it still waiting afterwards
        fresh = (await app_client.get(
            "/api/v1/interviews/turn?wait=0", headers={**ah, "X-AutoSkill-Client": "0.9.0"}
        )).json()
        assert fresh["status"] == "question"

        # no version header at all: nothing is forced, the interview simply goes on
        silent = (await app_client.get("/api/v1/interviews/turn?wait=0", headers=ah)).json()
        assert silent["status"] == "question"

        assert interview_service._version_key("0.10.0") > interview_service._version_key("0.9.0")
    finally:
        set_fake_provider(None)
