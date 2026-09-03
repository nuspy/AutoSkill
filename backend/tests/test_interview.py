"""End-to-end interview through the API with a scripted fake provider."""

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from tests.conftest import auth, register
from tests.test_gates_engine import complete_doc


def partial_doc() -> dict:
    doc = complete_doc()
    doc.human_confirmed = False
    doc.open_questions = ["Which folder holds the invoices?"]
    doc.data_sources[0].access = ""
    return doc.model_dump()


def filled_doc() -> dict:
    doc = complete_doc()
    doc.human_confirmed = False
    return doc.model_dump()


async def setup_project(app_client):
    user = await register(app_client, "alice@example.com")
    headers = auth(user["access_token"])
    project = (await app_client.post("/api/v1/projects", json={"name": "Ops"}, headers=headers)).json()
    return user, headers, project


async def test_interview_full_flow_with_supervisor_and_confirmation(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        fake.script(
            Scripted(purpose="interviewer", json=partial_doc()),  # intake
            Scripted(
                purpose="supervisor",
                json={
                    "decision": "proceed",
                    "reasons": ["looks fine"],
                    "missing": [],
                    "target_gate": None,
                    "next_question": None,
                    "confidence": 0.9,
                },
            ),
            Scripted(
                purpose="interviewer",
                json={
                    "question": "Where are the invoices stored?",
                    "why": "to open them",
                    "expects": "text",
                    "options": [],
                    "target_gate": "G2",
                },
            ),
        )
        created = await app_client.post(
            f"/api/v1/projects/{project['id']}/interviews",
            json={
                "title": "Invoice check",
                "description": "Every Monday I check supplier invoices in a spreadsheet.",
                "language": "en",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        sid = created.json()["id"]
        await get_job_runner().wait_all()

        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["state"] == "awaiting_answer"
        assert detail["waiting_for"] == "answer"
        # the supervisor said "proceed" but deterministic gates failed -> code overrode it
        assert detail["supervisor"]["effective"] == "need_more"
        assert detail["supervisor"]["failing_gate"] == "G2"
        assert detail["session"]["pending_question"]["question"] == "Where are the invoices stored?"
        assert detail["knowledge"]["completeness"]["passed"] < detail["knowledge"]["completeness"]["total"]
        assert [m["role"] for m in detail["messages"]] == ["assistant"]

        # answering while not awaiting the right input is rejected
        bad = await app_client.post(f"/api/v1/interviews/{sid}/confirm", json={"confirmed": True}, headers=headers)
        assert bad.status_code == 409

        fake.script(
            Scripted(purpose="interviewer", json=filled_doc()),  # ingest -> all gates pass except G8
            Scripted(
                purpose="interviewer", text="Here is what I understood: you check invoices every Monday."
            ),  # summary
        )
        answered = await app_client.post(
            f"/api/v1/interviews/{sid}/answer", json={"text": "On the shared drive, folder Invoices."}, headers=headers
        )
        assert answered.status_code == 200
        await get_job_runner().wait_all()
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["state"] == "awaiting_confirmation", detail["session"]
        assert detail["waiting_for"] == "confirmation"
        assert detail["knowledge"]["revision"] == 2
        assert "understood" in detail["session"]["pending_question"]["question"]

        # reject the summary with a correction -> back to the loop
        fake.script(
            Scripted(purpose="interviewer", json=filled_doc()),  # ingest correction
            Scripted(purpose="interviewer", text="Updated summary: invoices on Monday, flag over 1000."),
        )
        rejected = await app_client.post(
            f"/api/v1/interviews/{sid}/confirm",
            json={"confirmed": False, "text": "The limit is 1000 not 500"},
            headers=headers,
        )
        assert rejected.status_code == 200
        await get_job_runner().wait_all()
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["state"] == "awaiting_confirmation"
        assert detail["knowledge"]["revision"] == 4  # correction saved + ingest result

        # confirm -> finalize -> memory extracted
        fake.script(
            Scripted(
                purpose="interviewer",
                json={
                    "entries": [
                        {
                            "kind": "business_need",
                            "title": "Why invoices are checked",
                            "body": "Finance needs flagged invoices before payment.",
                        },
                        {
                            "kind": "integration_note",
                            "title": "Email notifications",
                            "body": "Uses SMTP with SMTP_PASSWORD.",
                            "structured": {"system": "email"},
                        },
                    ]
                },
            ),
        )
        confirmed = await app_client.post(
            f"/api/v1/interviews/{sid}/confirm", json={"confirmed": True}, headers=headers
        )
        assert confirmed.status_code == 200
        await get_job_runner().wait_all()
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["state"] == "complete", detail["session"]
        assert detail["procedure_state"] == "completed"
        assert detail["knowledge"]["frozen"] is True and detail["knowledge"]["doc"]["human_confirmed"] is True
        assert detail["session"]["token_usage"]["input_tokens"] > 0

        skill_id = detail["session"]["skill_id"]
        skill = (await app_client.get(f"/api/v1/skills/{skill_id}", headers=headers)).json()
        assert skill["name"] == "invoice-check" and skill["latest_interview_state"] == "complete"
        assert skill["title"] == "Invoice check"
        memory = (await app_client.get(f"/api/v1/skills/{skill_id}/memory", headers=headers)).json()
        assert {m["kind"] for m in memory} == {"business_need", "integration_note"}
        assert all(m["source"] == "interview" for m in memory)
        # every LLM call carried a purpose and the supervisor ran at temperature 0
        supervisor_calls = [c for c in fake.calls if c.purpose == "supervisor"]
        assert supervisor_calls and all(c.temperature == 0.0 for c in supervisor_calls)
    finally:
        set_fake_provider(None)


async def test_interview_supervisor_block_and_provider_failure(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        fake.script(
            Scripted(purpose="interviewer", json=partial_doc()),
            Scripted(
                purpose="supervisor",
                json={
                    "decision": "block",
                    "reasons": ["task requires physical presence"],
                    "missing": [],
                    "confidence": 0.9,
                },
            ),
        )
        created = await app_client.post(
            f"/api/v1/projects/{project['id']}/interviews",
            json={"title": "Water plants", "description": "I water the office plants."},
            headers=headers,
        )
        sid = created.json()["id"]
        await get_job_runner().wait_all()
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["state"] == "failed"
        assert "physical presence" in detail["session"]["error"]
        assert detail["procedure_state"] == "completed"

        # provider returning garbage forever -> procedure fails, session marked failed with the error
        fake.capabilities.json_schema = False
        fake.capabilities.tools = False
        created = await app_client.post(
            f"/api/v1/projects/{project['id']}/interviews",
            json={"title": "Broken", "description": "x"},
            headers=headers,
        )
        sid = created.json()["id"]
        await get_job_runner().wait_all()
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        assert detail["session"]["state"] == "failed" and "structured output failed" in detail["session"]["error"]
    finally:
        set_fake_provider(None)


async def test_interview_requires_provider_when_no_fake(app_client):
    user, headers, project = await setup_project(app_client)
    created = await app_client.post(
        f"/api/v1/projects/{project['id']}/interviews", json={"title": "T", "description": "d"}, headers=headers
    )
    assert created.status_code == 201
    await get_job_runner().wait_all()
    detail = (await app_client.get(f"/api/v1/interviews/{created.json()['id']}", headers=headers)).json()
    assert detail["session"]["state"] == "failed" and "No LLM provider" in detail["session"]["error"]


async def test_skill_suspend_resume_and_memory_management(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        fake.script(
            Scripted(purpose="interviewer", json=partial_doc()),
            Scripted(
                purpose="supervisor",
                json={
                    "decision": "need_more",
                    "reasons": [],
                    "missing": ["folder"],
                    "target_gate": "G2",
                    "next_question": "Which folder?",
                    "confidence": 0.5,
                },
            ),
            Scripted(
                purpose="interviewer",
                json={"question": "Which folder?", "why": "", "expects": "text", "options": [], "target_gate": "G2"},
            ),
        )
        created = await app_client.post(
            f"/api/v1/projects/{project['id']}/interviews",
            json={"title": "Invoice check", "description": "desc"},
            headers=headers,
        )
        await get_job_runner().wait_all()
        skill_id = created.json()["skill_id"]
    finally:
        set_fake_provider(None)

    suspended = await app_client.post(
        f"/api/v1/skills/{skill_id}/suspend", json={"note": "waiting for IT"}, headers=headers
    )
    assert suspended.json()["development_state"] == "suspended"
    blocked = await app_client.post(
        f"/api/v1/projects/{project['id']}/interviews",
        json={"title": "x", "description": "d", "skill_id": skill_id},
        headers=headers,
    )
    assert blocked.status_code == 409
    resumed = await app_client.post(f"/api/v1/skills/{skill_id}/resume", headers=headers)
    assert resumed.json()["development_state"] == "active"

    entry = await app_client.post(
        f"/api/v1/skills/{skill_id}/memory",
        json={"kind": "rationale", "title": "Why Monday", "body": "Invoices arrive on Friday."},
        headers=headers,
    )
    assert entry.status_code == 201
    eid = entry.json()["id"]
    bad = await app_client.post(
        f"/api/v1/skills/{skill_id}/memory", json={"kind": "nope", "title": "t", "body": "b"}, headers=headers
    )
    assert bad.status_code == 422
    newer = await app_client.post(
        f"/api/v1/skills/{skill_id}/memory/{eid}/supersede",
        json={"title": "Why Monday", "body": "Invoices arrive Friday; Monday leaves time."},
        headers=headers,
    )
    assert newer.status_code == 200
    active = (await app_client.get(f"/api/v1/skills/{skill_id}/memory", headers=headers)).json()
    assert [m["id"] for m in active] == [newer.json()["id"]]
    everything = (await app_client.get(f"/api/v1/skills/{skill_id}/memory?status=all", headers=headers)).json()
    old = next(m for m in everything if m["id"] == eid)
    assert old["status"] == "superseded" and old["superseded_by_id"] == newer.json()["id"]
    archived = await app_client.post(
        f"/api/v1/skills/{skill_id}/memory/{newer.json()['id']}/status/archived", headers=headers
    )
    assert archived.json()["status"] == "archived"
    assert (await app_client.get(f"/api/v1/skills/{skill_id}/memory", headers=headers)).json() == []


async def test_providers_and_data_sources_api(app_client):
    user, headers, project = await setup_project(app_client)
    bob = await register(app_client, "bob@example.com")
    b = auth(bob["access_token"])
    # system provider: admin only
    denied = await app_client.post(
        "/api/v1/providers", json={"name": "Ollama", "adapter": "openai_compat", "model": "llama3"}, headers=b
    )
    assert denied.status_code == 403
    created = await app_client.post(
        "/api/v1/providers",
        json={
            "name": "Ollama",
            "adapter": "openai_compat",
            "model": "llama3",
            "base_url": "http://localhost:11434/v1",
            "api_key": "secret",
            "is_default": True,
            "purposes": ["interviewer"],
        },
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["has_api_key"] is True and "secret" not in created.text
    unknown = await app_client.post(
        "/api/v1/providers", json={"name": "x", "adapter": "magic", "model": "m"}, headers=headers
    )
    assert unknown.status_code == 422
    listed = await app_client.get("/api/v1/providers", headers=b)
    assert len(listed.json()) == 1 and listed.json()[0]["scope"] == "system"
    # project provider by owner
    pp = await app_client.post(
        f"/api/v1/providers?project_id={project['id']}",
        json={"name": "Claude", "adapter": "anthropic", "model": "claude-sonnet-5", "api_key": "k"},
        headers=headers,
    )
    assert pp.status_code == 201 and pp.json()["scope"] == "project"
    # test connection fails gracefully (no server at that url)
    test = await app_client.post(f"/api/v1/providers/{created.json()['id']}/test", headers=headers)
    assert test.status_code == 200 and test.json()["ok"] is False

    ds = await app_client.post(
        f"/api/v1/projects/{project['id']}/data-sources",
        json={
            "name": "Invoices",
            "kind": "spreadsheet",
            "access_notes": "shared drive",
            "schema_def": {"columns": ["number"]},
        },
        headers=headers,
    )
    assert ds.status_code == 201 and ds.json()["schema_def"] == {"columns": ["number"]}
    bad_kind = await app_client.post(
        f"/api/v1/projects/{project['id']}/data-sources", json={"name": "X", "kind": "hologram"}, headers=headers
    )
    assert bad_kind.status_code == 422
    upd = await app_client.patch(
        f"/api/v1/projects/{project['id']}/data-sources/{ds.json()['id']}", json={"sensitivity": "pii"}, headers=headers
    )
    assert upd.json()["sensitivity"] == "pii"
    assert len((await app_client.get(f"/api/v1/projects/{project['id']}/data-sources", headers=headers)).json()) == 1
