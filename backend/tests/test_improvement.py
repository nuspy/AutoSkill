"""Improvement loop: analysis clusters, proposal job -> patch version + rationale, human decision, cron scan."""

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from autoskill.services.improvement.analyzer import error_signature, should_trigger
from tests.conftest import auth
from tests.test_interview import setup_project
from tests.test_packaging import sample_spec
from tests.test_trials import make_draft

ANALYST = {
    "hypotheses": ["Step flag misses rows when the amount column has a currency symbol"],
    "instructions": "In step flag, strip currency symbols before comparing amounts.",
    "rationale": "Three runs failed in step flag with a conversion error; stripping symbols fixes the comparison.",
    "memory_entries": [
        {
            "kind": "lesson_learned",
            "title": "Amounts carry currency symbols",
            "body": "Strip € before float()",
            "step_key": "flag",
        }
    ],
}


def test_error_signature_normalises():
    assert error_signature({"message": "could not convert '€ 1.200' at row 12"}) == error_signature(
        {"message": "could not convert '€ 3.400' at row 7"}
    )
    assert error_signature(None) == "unknown"
    assert should_trigger({"runs_failed": 3, "issues": 0}) == "auto_failure_threshold"
    assert should_trigger({"runs_failed": 0, "issues": 2}) == "issue_reports"
    assert should_trigger({"runs_failed": 1, "issues": 1}) is None


async def record_failures(app_client, key: str, n: int = 3):
    kh = auth(key)
    for i in range(n):
        run = (
            await app_client.post(
                "/api/v1/telemetry/runs", json={"skill_name": "invoice-check", "skill_version": "0.1.0"}, headers=kh
            )
        ).json()
        await app_client.post(
            f"/api/v1/telemetry/runs/{run['run_id']}/steps",
            json={"step_key": "open-sheet", "status": "succeeded"},
            headers=kh,
        )
        await app_client.post(
            f"/api/v1/telemetry/runs/{run['run_id']}/steps",
            json={
                "step_key": "flag",
                "status": "failed",
                "error": {"message": f"could not convert '€ 1.{i}00' at row {i}"},
            },
            headers=kh,
        )
        await app_client.post(
            f"/api/v1/telemetry/runs/{run['run_id']}/end",
            json={"status": "failed", "error": {"message": "flag failed"}},
            headers=kh,
        )


async def test_proposal_flow_and_decisions(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)
        key = (
            await app_client.post(
                f"/api/v1/projects/{project['id']}/api-keys",
                json={"name": "t", "scopes": ["telemetry:write"]},
                headers=headers,
            )
        ).json()["key"]
        # nothing to improve yet -> proposal fails gracefully
        empty = await app_client.post(
            f"/api/v1/skills/{skill_id}/improvements", json={"base_version_id": version["id"]}, headers=headers
        )
        assert empty.status_code == 202
        await get_job_runner().wait_all()
        first = (await app_client.get(f"/api/v1/improvements/{empty.json()['id']}", headers=headers)).json()
        assert first["state"] == "failed" and "nothing to improve" in first["error"]

        await record_failures(app_client, key)
        await app_client.post(
            "/api/v1/telemetry/issues",
            json={
                "skill_name": "invoice-check",
                "step_key": "flag",
                "severity": "high",
                "description": "amounts with € are skipped",
            },
            headers=auth(key),
        )
        analysis = (
            await app_client.get(
                f"/api/v1/skills/{skill_id}/improvements/analysis?version_id={version['id']}", headers=headers
            )
        ).json()
        assert analysis["runs_failed"] == 3 and analysis["issues"] == 1
        top = analysis["clusters"][0]
        assert top["step_key"] == "flag" and top["count"] == 3 and top["step_title"] == "Flag anomalies"

        fake.script(
            Scripted(purpose="analyst", json=ANALYST),
            Scripted(purpose="author", json={**sample_spec().model_dump(), "changelog": "strip currency symbols"}),
            # memory extraction from the analysis (job memory.extract, provider "analyst")
            Scripted(
                purpose="analyst",
                json={"entries": [{"kind": "lesson_learned", "title": "From analysis", "body": "Amounts vary."}]},
            ),
        )
        created = await app_client.post(
            f"/api/v1/skills/{skill_id}/improvements", json={"base_version_id": version["id"]}, headers=headers
        )
        assert created.status_code == 202
        dup = await app_client.post(
            f"/api/v1/skills/{skill_id}/improvements", json={"base_version_id": version["id"]}, headers=headers
        )
        assert dup.status_code == 409
        await get_job_runner().wait_all()
        proposals = (await app_client.get(f"/api/v1/skills/{skill_id}/improvements", headers=headers)).json()
        prop = next(p for p in proposals if p["id"] == created.json()["id"])
        assert prop["state"] == "proposed", prop
        assert prop["proposed_version_id"] and prop["rationale"].startswith("Three runs failed")
        assert prop["analysis"]["hypotheses"] == ANALYST["hypotheses"] and len(prop["source_run_ids"]) == 3
        assert any(
            m["title"] == "From analysis" and m["source"] == "improvement" and m["status"] == "proposed"
            for m in (await app_client.get(f"/api/v1/skills/{skill_id}/memory?status=all", headers=headers)).json()
        )
        assert prop["diff_summary"]["suggested_bump"] in ("patch", "minor")
        versions = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)).json()
        newest = versions[0]
        assert (
            newest["id"] == prop["proposed_version_id"]
            and newest["origin"] == "improvement"
            and newest["state"] == "draft"
            and newest["created_by"] == "system"
        )
        assert newest["rationale"].startswith("Three runs failed")
        author_prompt = [c for c in fake.calls if c.purpose == "author"][-1].messages[-1].content
        assert "strip currency symbols" in author_prompt.lower()
        # proposed memory is not active until accepted
        assert not any(
            m["title"] == "Amounts carry currency symbols"
            for m in (await app_client.get(f"/api/v1/skills/{skill_id}/memory", headers=headers)).json()
        )
        # owners were notified
        notes = (await app_client.get("/api/v1/me/notifications", headers=headers)).json()["items"]
        assert any(n["kind"] == "proposal_ready" for n in notes)

        # opening marks it under review; accepting activates memory, the version stays a draft (goes through trial)
        detail = (await app_client.get(f"/api/v1/improvements/{prop['id']}", headers=headers)).json()
        assert detail["state"] == "under_review"
        accepted = await app_client.post(
            f"/api/v1/improvements/{prop['id']}/decision",
            json={"accept": True, "comment": "makes sense"},
            headers=headers,
        )
        assert accepted.status_code == 200 and accepted.json()["state"] == "accepted"
        assert any(
            m["title"] == "Amounts carry currency symbols" and m["source"] == "improvement"
            for m in (await app_client.get(f"/api/v1/skills/{skill_id}/memory", headers=headers)).json()
        )
        assert (await app_client.get(f"/api/v1/versions/{newest['id']}", headers=headers)).json()["state"] == "draft"

        # a rejected proposal discards its version
        fake.script(
            Scripted(purpose="analyst", json=ANALYST),
            Scripted(purpose="author", json={**sample_spec().model_dump(), "changelog": "v3"}),
        )
        second = (
            await app_client.post(
                f"/api/v1/skills/{skill_id}/improvements", json={"base_version_id": version["id"]}, headers=headers
            )
        ).json()
        await get_job_runner().wait_all()
        second = (await app_client.get(f"/api/v1/improvements/{second['id']}", headers=headers)).json()
        assert second["state"] == "under_review"
        rejected = await app_client.post(
            f"/api/v1/improvements/{second['id']}/decision", json={"accept": False, "comment": "no"}, headers=headers
        )
        assert rejected.json()["state"] == "rejected"
        assert (await app_client.get(f"/api/v1/versions/{second['proposed_version_id']}", headers=headers)).json()[
            "state"
        ] == "discarded"
        twice = await app_client.post(
            f"/api/v1/improvements/{second['id']}/decision", json={"accept": True}, headers=headers
        )
        assert twice.status_code == 409
    finally:
        set_fake_provider(None)


async def test_scan_opens_proposals_automatically(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)
        # scan only looks at tested/published versions: move to testing then tested via a trial
        from tests.test_review import accepted_trial

        await accepted_trial(app_client, headers, version["id"], fake)
        key = (
            await app_client.post(
                f"/api/v1/projects/{project['id']}/api-keys",
                json={"name": "t", "scopes": ["telemetry:write"]},
                headers=headers,
            )
        ).json()["key"]
        await record_failures(app_client, key, n=3)
        fake.script(
            Scripted(purpose="analyst", json=ANALYST),
            Scripted(purpose="author", json={**sample_spec().model_dump(), "changelog": "auto"}),
        )
        runner = get_job_runner()
        await runner.enqueue("improvement.scan", {})
        await runner.wait_all()
        proposals = (await app_client.get(f"/api/v1/skills/{skill_id}/improvements", headers=headers)).json()
        assert (
            len(proposals) == 1
            and proposals[0]["trigger"] == "auto_failure_threshold"
            and proposals[0]["state"] == "proposed"
        )
        # a second scan does not duplicate while one is open
        await runner.enqueue("improvement.scan", {})
        await runner.wait_all()
        assert len((await app_client.get(f"/api/v1/skills/{skill_id}/improvements", headers=headers)).json()) == 1
    finally:
        set_fake_provider(None)
