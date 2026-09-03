"""Local trial flow: request -> install -> phased checkpoints -> coach -> outcome; telemetry API."""

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from tests.test_drafting import run_interview_to_completion
from tests.test_interview import setup_project
from tests.test_packaging import sample_spec


async def make_draft(app_client, headers, project, fake):
    sid = await run_interview_to_completion(app_client, headers, project, fake)
    fake.script(Scripted(purpose="author", json=sample_spec().model_dump()))
    await app_client.post(f"/api/v1/interviews/{sid}/confirm", json={"confirmed": True}, headers=headers)
    await get_job_runner().wait_all()
    skill_id = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()["session"]["skill_id"]
    version = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)).json()[0]
    return skill_id, version


def trial_headers(token: str) -> dict:
    return {"X-AutoSkill-Trial": token}


async def test_interactive_trial_full_cycle(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)
        created = await app_client.post(
            "/api/v1/trials",
            json={"skill_version_id": version["id"], "target_agent": "hermes", "purpose": "develop"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        trial = created.json()
        token = trial["session_token"]
        assert (
            trial["state"] == "requested"
            and "autoskill trial install invoice-check@0.1.0 --target hermes" in trial["cli_command"]
        )
        assert (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)).json()[0][
            "state"
        ] == "testing"
        dup = await app_client.post(
            "/api/v1/trials", json={"skill_version_id": version["id"], "target_agent": "hermes"}, headers=headers
        )
        assert dup.status_code == 409
        bad_target = await app_client.post(
            "/api/v1/trials", json={"skill_version_id": version["id"], "target_agent": "emacs"}, headers=headers
        )
        assert bad_target.status_code == 422

        # the CLI downloads the trial package (marked as trial) and reports the installation
        pkg = await app_client.get(f"/api/v1/trials/{trial['id']}/package.zip", headers=headers)
        assert pkg.status_code == 200
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(pkg.content)) as zf:
            md = zf.read("invoice-check/SKILL.md").decode()
            assert f"autoskill_trial: {trial['id']}" in md
            assert "invoice-check/INSTALL.hermes.md" in zf.namelist()
        inst = await app_client.post(
            f"/api/v1/trials/{trial['id']}/installed",
            json={"install_manifest": {"skill_dir": "~/.hermes/skills/invoice-check", "build": 1}, "build": 1},
            headers=headers,
        )
        assert inst.json()["state"] == "installed"

        # the agent (via the companion) starts a run with the trial token only
        run = await app_client.post(
            "/api/v1/telemetry/runs",
            json={"skill_name": "invoice-check", "agent_target": "hermes"},
            headers=trial_headers(token),
        )
        assert run.status_code == 200, run.text
        run_id = run.json()["run_id"]
        assert run.json()["mode"] == "interactive" and run.json()["trial_session_id"] == trial["id"]
        detail = (await app_client.get(f"/api/v1/trials/{trial['id']}", headers=headers)).json()
        assert detail["trial"]["state"] == "testing"

        # phase ordering is enforced: preview before explain is rejected
        early = await app_client.post(
            "/api/v1/checkpoints",
            json={"run_id": run_id, "step_key": "open-sheet", "phase": "preview"},
            headers=trial_headers(token),
        )
        assert early.status_code == 409 and early.json()["error"]["code"] == "explain_required"
        unknown = await app_client.post(
            "/api/v1/checkpoints",
            json={"run_id": run_id, "step_key": "nope", "phase": "explain"},
            headers=trial_headers(token),
        )
        assert unknown.status_code == 422

        cp = (
            await app_client.post(
                "/api/v1/checkpoints",
                json={
                    "run_id": run_id,
                    "step_key": "open-sheet",
                    "phase": "explain",
                    "proposal": {"explanation": "I will open Invoices.xlsx", "tools": ["read_file"]},
                },
                headers=trial_headers(token),
            )
        ).json()
        assert cp["status"] == "pending"
        pending = (
            await app_client.get(f"/api/v1/checkpoints/{cp['checkpoint_id']}?wait=0", headers=trial_headers(token))
        ).json()
        assert pending["status"] == "pending"
        detail = (await app_client.get(f"/api/v1/trials/{trial['id']}", headers=headers)).json()
        assert (
            detail["pending_checkpoint"]["phase"] == "explain" and detail["trial"]["current_step_key"] == "open-sheet"
        )

        # human decides from the web UI; a wrong decision for the phase is rejected
        wrong = await app_client.post(
            f"/api/v1/checkpoints/{cp['checkpoint_id']}/decision",
            json={"decision": "approve_and_authorize_next"},
            headers=headers,
        )
        assert wrong.status_code == 422
        ok = await app_client.post(
            f"/api/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"decision": "continue"}, headers=headers
        )
        assert ok.status_code == 200 and ok.json()["decision"] == "continue"
        decided = (
            await app_client.get(f"/api/v1/checkpoints/{cp['checkpoint_id']}?wait=5", headers=trial_headers(token))
        ).json()
        assert decided["status"] == "decided" and decided["decision"] == "continue"
        again = await app_client.post(
            f"/api/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"decision": "continue"}, headers=headers
        )
        assert again.status_code == 409

        # preview with real data -> the person asks for a change through the coach
        prev = (
            await app_client.post(
                "/api/v1/checkpoints",
                json={
                    "run_id": run_id,
                    "step_key": "open-sheet",
                    "phase": "preview",
                    "proposal": {
                        "data_preview": [{"number": "A1", "amount": 1200, "email": "x@y.com"}],
                        "planned_effect": "none",
                    },
                },
                headers=trial_headers(token),
            )
        ).json()
        assert prev["status"] == "pending"
        fake.script(
            Scripted(
                purpose="coach",
                json={
                    "reply": "Sure, I will only open the current month sheet.",
                    "no_change": False,
                    "new_instruction": "Open Invoices.xlsx and select the sheet named with the current month.",
                    "change_summary": "select current month sheet",
                    "memory_entries": [
                        {
                            "kind": "technical_note",
                            "title": "Monthly sheets",
                            "body": "The workbook has one sheet per month.",
                        }
                    ],
                },
            )
        )
        disc = await app_client.post(
            f"/api/v1/checkpoints/{prev['checkpoint_id']}/discussion",
            json={"message": "It should open only this month's sheet"},
            headers=headers,
        )
        assert disc.status_code == 200, disc.text
        assert disc.json()["messages"][-1]["proposal"]["new_instruction"].startswith("Open Invoices.xlsx and select")
        applied = await app_client.post(f"/api/v1/discussions/{disc.json()['id']}/apply", headers=headers)
        assert (
            applied.status_code == 200
            and applied.json()["state"] == "closed"
            and applied.json()["outcome"]["instruction_updated"] is True
        )
        # the checkpoint got a 'change' decision with the updated instruction, package rebuilt (build 2), memory stored
        changed = (
            await app_client.get(f"/api/v1/checkpoints/{prev['checkpoint_id']}?wait=0", headers=trial_headers(token))
        ).json()
        assert (
            changed["decision"] == "change"
            and "current month" in changed["updated_instructions"]
            and changed["iteration"] == 1
        )
        vd = (await app_client.get(f"/api/v1/versions/{version['id']}", headers=headers)).json()
        assert vd["build"] == 2 and vd["state"] == "testing"
        assert next(s for s in vd["steps"] if s["key"] == "open-sheet")["test_status"] == "corrected"
        md = (await app_client.get(f"/api/v1/versions/{version['id']}/files/SKILL.md", headers=headers)).json()[
            "content"
        ]
        assert "select the sheet named with the current month" in md and "build: '2'" in md
        memory = (await app_client.get(f"/api/v1/skills/{skill_id}/memory", headers=headers)).json()
        assert any(
            m["title"] == "Monthly sheets" and m["source"] == "trial_discussion" and m["step_key"] == "open-sheet"
            for m in memory
        )
        sync = (await app_client.get(f"/api/v1/trials/{trial['id']}/sync", headers=headers)).json()
        assert sync["stale"] is True and sync["current_build"] == 2
        await app_client.post(
            f"/api/v1/trials/{trial['id']}/installed",
            json={"install_manifest": {"build": 2}, "build": 2},
            headers=headers,
        )
        assert (await app_client.get(f"/api/v1/trials/{trial['id']}/sync", headers=headers)).json()["stale"] is False
        guidance = (
            await app_client.get(f"/api/v1/telemetry/guidance/{skill_id}/open-sheet", headers=trial_headers(token))
        ).json()
        assert (
            guidance["corrections"][0]["text"] == "select current month sheet"
            and guidance["memory"][0]["title"] == "Monthly sheets"
        )

        # iteration 2: explain -> preview -> verify -> approve and authorize next
        detail = (await app_client.get(f"/api/v1/trials/{trial['id']}", headers=headers)).json()
        assert detail["trial"]["current_iteration"] == 2
        for phase, decision in (
            ("explain", "continue"),
            ("preview", "continue"),
            ("verify", "approve_and_authorize_next"),
        ):
            c = (
                await app_client.post(
                    "/api/v1/checkpoints",
                    json={"run_id": run_id, "step_key": "open-sheet", "phase": phase, "proposal": {"phase": phase}},
                    headers=trial_headers(token),
                )
            ).json()
            assert c["status"] == "pending", (phase, c)
            r = await app_client.post(
                f"/api/v1/checkpoints/{c['checkpoint_id']}/decision", json={"decision": decision}, headers=headers
            )
            assert r.status_code == 200, r.text
        # a read-only step runs for real; the next step cannot start until the previous is approved
        step = next(
            s
            for s in (await app_client.get(f"/api/v1/versions/{version['id']}", headers=headers)).json()["steps"]
            if s["key"] == "open-sheet"
        )
        assert step["test_status"] == "corrected" and step["confirmations_count"] == 1

        # step 2 (reversible, sandbox copy) - approve quickly; step 3 is irreversible: execute needs explicit authorization
        for phase, decision in (
            ("explain", "continue"),
            ("preview", "continue"),
            ("verify", "approve_and_authorize_next"),
        ):
            c = (
                await app_client.post(
                    "/api/v1/checkpoints",
                    json={"run_id": run_id, "step_key": "flag", "phase": phase},
                    headers=trial_headers(token),
                )
            ).json()
            assert c["status"] == "pending"
            await app_client.post(
                f"/api/v1/checkpoints/{c['checkpoint_id']}/decision", json={"decision": decision}, headers=headers
            )
        c = (
            await app_client.post(
                "/api/v1/checkpoints",
                json={"run_id": run_id, "step_key": "send", "phase": "explain"},
                headers=trial_headers(token),
            )
        ).json()
        await app_client.post(
            f"/api/v1/checkpoints/{c['checkpoint_id']}/decision", json={"decision": "continue"}, headers=headers
        )
        c = (
            await app_client.post(
                "/api/v1/checkpoints",
                json={
                    "run_id": run_id,
                    "step_key": "send",
                    "phase": "preview",
                    "proposal": {"planned_effect": "email to accounting@corp with 3 rows"},
                },
                headers=trial_headers(token),
            )
        ).json()
        await app_client.post(
            f"/api/v1/checkpoints/{c['checkpoint_id']}/decision", json={"decision": "continue"}, headers=headers
        )
        execute = await app_client.post(
            "/api/v1/checkpoints",
            json={"run_id": run_id, "step_key": "send", "phase": "execute"},
            headers=trial_headers(token),
        )
        assert execute.status_code == 409 and execute.json()["error"]["code"] == "simulated_step"
        verify = (
            await app_client.post(
                "/api/v1/checkpoints",
                json={"run_id": run_id, "step_key": "send", "phase": "verify", "proposal": {"simulated": True}},
                headers=trial_headers(token),
            )
        ).json()
        await app_client.post(
            f"/api/v1/checkpoints/{verify['checkpoint_id']}/decision",
            json={"decision": "approve_and_authorize_next"},
            headers=headers,
        )

        # log steps + end run through the same trial token, then summary and outcome
        logged = await app_client.post(
            f"/api/v1/telemetry/runs/{run_id}/steps",
            json={"step_key": "open-sheet", "status": "succeeded", "outputs": {"rows": 12, "contact": "boss@corp.com"}},
            headers={**trial_headers(token), "Idempotency-Key": "k1"},
        )
        assert logged.status_code == 200
        await app_client.post(
            f"/api/v1/telemetry/runs/{run_id}/steps",
            json={"step_key": "open-sheet", "status": "succeeded"},
            headers={**trial_headers(token), "Idempotency-Key": "k1"},
        )
        ended = await app_client.post(
            f"/api/v1/telemetry/runs/{run_id}/end",
            json={"status": "succeeded", "summary": "done, mail me at a@b.co"},
            headers=trial_headers(token),
        )
        assert ended.status_code == 200
        rd = (await app_client.get(f"/api/v1/runs/{run_id}", headers=headers)).json()
        assert (
            len(rd["steps"]) == 1
            and rd["steps"][0]["outputs"]["contact"] == "<email>"
            and rd["run"]["summary"].endswith("<email>")
        )
        assert len(rd["checkpoints"]) >= 10

        fake.script(
            Scripted(purpose="coach", text="All three steps confirmed; step 'send' was simulated. Recommend: accept.")
        )
        summarized = await app_client.post(f"/api/v1/trials/{trial['id']}/summary", headers=headers)
        assert summarized.json()["state"] == "reviewing" and "simulated" in summarized.json()["summary"]
        accepted = await app_client.post(
            f"/api/v1/trials/{trial['id']}/outcome",
            json={"outcome": "accepted", "keep_installed": True},
            headers=headers,
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["state"] == "decided" and accepted.json()["keep_installed"] is True
        assert (await app_client.get(f"/api/v1/versions/{version['id']}", headers=headers)).json()["state"] == "tested"
        runs = (await app_client.get(f"/api/v1/projects/{project['id']}/runs", headers=headers)).json()
        assert runs[0]["human_feedback"] == "corrected" and runs[0]["source"] == "trial"
        # the token is dead once the trial is closed
        dead = await app_client.post(
            "/api/v1/telemetry/runs", json={"skill_name": "invoice-check"}, headers=trial_headers(token)
        )
        assert dead.status_code == 404
    finally:
        set_fake_provider(None)


async def test_async_trial_auto_decides_and_changes_requested_spawns_patch(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)
        trial = (
            await app_client.post(
                "/api/v1/trials",
                json={"skill_version_id": version["id"], "target_agent": "openclaw", "mode": "async"},
                headers=headers,
            )
        ).json()
        token = trial["session_token"]
        run_id = (await app_client.post("/api/v1/telemetry/runs", json={}, headers=trial_headers(token))).json()[
            "run_id"
        ]
        for phase in ("explain", "preview", "verify"):
            c = (
                await app_client.post(
                    "/api/v1/checkpoints",
                    json={"run_id": run_id, "step_key": "open-sheet", "phase": phase},
                    headers=trial_headers(token),
                )
            ).json()
            assert c["status"] == "decided"
        assert c["decision"] == "approve_and_authorize_next"
        # irreversible step: the preview is auto-continued but execute still needs the human
        for phase in ("explain", "preview"):
            c = (
                await app_client.post(
                    "/api/v1/checkpoints",
                    json={"run_id": run_id, "step_key": "send", "phase": phase},
                    headers=trial_headers(token),
                )
            ).json()
        assert c["decision"] == "continue"
        execute = await app_client.post(
            "/api/v1/checkpoints",
            json={"run_id": run_id, "step_key": "send", "phase": "execute"},
            headers=trial_headers(token),
        )
        assert execute.status_code == 409

        # suspend / resume
        assert (await app_client.post(f"/api/v1/trials/{trial['id']}/suspend", headers=headers)).json()[
            "state"
        ] == "suspended"
        assert (await app_client.post(f"/api/v1/trials/{trial['id']}/resume", headers=headers)).json()[
            "state"
        ] == "testing"

        # accepting with unconfirmed steps is refused for a development trial
        refused = await app_client.post(
            f"/api/v1/trials/{trial['id']}/outcome", json={"outcome": "accepted"}, headers=headers
        )
        assert refused.status_code == 422 and "flag" in refused.json()["error"]["details"]["steps"]

        fake.script(Scripted(purpose="author", json={**sample_spec().model_dump(), "changelog": "v2 after trial"}))
        changed = await app_client.post(
            f"/api/v1/trials/{trial['id']}/outcome",
            json={"outcome": "changes_requested", "note": "rename the flag step"},
            headers=headers,
        )
        assert changed.json()["state"] == "decided" and changed.json()["outcome"] == "changes_requested"
        await get_job_runner().wait_all()
        versions = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)).json()
        assert [v["version"] for v in versions] == ["0.1.1", "0.1.0"] and versions[0]["origin"] == "trial_corrections"
        author_prompt = [c for c in fake.calls if c.purpose == "author"][-1].messages[-1].content
        assert "rename the flag step" in author_prompt
    finally:
        set_fake_provider(None)


async def test_project_key_telemetry_and_issues(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)
    finally:
        set_fake_provider(None)
    key = (
        await app_client.post(
            f"/api/v1/projects/{project['id']}/api-keys",
            json={"name": "t", "scopes": ["telemetry:write"]},
            headers=headers,
        )
    ).json()["key"]
    kh = {"Authorization": f"Bearer {key}"}
    run = await app_client.post(
        "/api/v1/telemetry/runs",
        json={"skill_name": "invoice-check", "skill_version": "0.1.0", "agent_target": "hermes"},
        headers=kh,
    )
    assert run.status_code == 200 and run.json()["mode"] == "production"
    run_id = run.json()["run_id"]
    # production runs create auto-decided checkpoints (no trial): the agent never blocks
    c = (
        await app_client.post(
            "/api/v1/checkpoints", json={"run_id": run_id, "step_key": "open-sheet", "phase": "explain"}, headers=kh
        )
    ).json()
    assert c["status"] == "decided" and c["decision"] == "continue"
    unknown = await app_client.post("/api/v1/telemetry/runs", json={"skill_name": "nope"}, headers=kh)
    assert unknown.status_code == 404
    assert (
        await app_client.post(
            f"/api/v1/telemetry/runs/{run_id}/end", json={"status": "failed", "error": {"message": "boom"}}, headers=kh
        )
    ).status_code == 200
    twice = await app_client.post(f"/api/v1/telemetry/runs/{run_id}/end", json={"status": "failed"}, headers=kh)
    assert twice.status_code == 409
    issue = await app_client.post(
        "/api/v1/telemetry/issues",
        json={"skill_name": "invoice-check", "step_key": "flag", "severity": "high", "description": "column missing"},
        headers=kh,
    )
    assert issue.status_code == 200
    runs = (await app_client.get(f"/api/v1/projects/{project['id']}/runs", headers=headers)).json()
    assert {r["status"] for r in runs} == {"failed", "needs_review"}
    needs = next(r for r in runs if r["status"] == "needs_review")
    rd = (await app_client.get(f"/api/v1/runs/{needs['id']}", headers=headers)).json()
    assert rd["annotations"][0]["kind"] == "issue" and rd["annotations"][0]["severity"] == "high"
    golden = await app_client.patch(
        f"/api/v1/runs/{run_id}", json={"is_golden": True, "human_feedback": "wrong"}, headers=headers
    )
    assert golden.json()["is_golden"] is True
    no_auth = await app_client.post("/api/v1/telemetry/runs", json={"skill_name": "invoice-check"})
    assert no_auth.status_code == 401
