"""Version lifecycle: state machine guards, review queue, decisions, human authorization, diff."""

import pytest

from autoskill.core.jobs import get_job_runner
from autoskill.db.session import get_session_factory
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from autoskill.models.skill_version import SkillVersion
from autoskill.services.versioning.state_machine import allowed_targets, transition
from tests.conftest import auth, register
from tests.test_interview import setup_project
from tests.test_packaging import sample_spec
from tests.test_trials import make_draft, trial_headers


async def accepted_trial(app_client, headers, version_id: str, fake: FakeLlmProvider) -> None:
    """Run an async trial through all steps and accept it -> version 'tested'."""
    trial = (
        await app_client.post(
            "/api/v1/trials",
            json={"skill_version_id": version_id, "target_agent": "hermes", "mode": "async"},
            headers=headers,
        )
    ).json()
    token = trial["session_token"]
    run_id = (await app_client.post("/api/v1/telemetry/runs", json={}, headers=trial_headers(token))).json()["run_id"]
    for step in ("open-sheet", "flag", "send"):
        for phase in ("explain", "preview", "verify"):
            r = await app_client.post(
                "/api/v1/checkpoints",
                json={"run_id": run_id, "step_key": step, "phase": phase},
                headers=trial_headers(token),
            )
            assert r.status_code == 200, r.text
    await app_client.post(
        f"/api/v1/telemetry/runs/{run_id}/end", json={"status": "succeeded"}, headers=trial_headers(token)
    )
    fake.script(Scripted(purpose="coach", text="fine"))
    r = await app_client.post(
        f"/api/v1/trials/{trial['id']}/outcome", json={"outcome": "accepted", "keep_installed": True}, headers=headers
    )
    assert r.status_code == 200, r.text


async def test_state_machine_guards(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)
    finally:
        set_fake_provider(None)
    assert allowed_targets("draft") == ["discarded", "testing"]
    assert allowed_targets("approved") == ["published"]
    async with get_session_factory()() as session:
        v = await session.get(SkillVersion, version["id"])
        # system can enter testing but not skip to tested with unconfirmed steps
        await transition(session, v, "testing", actor=None)
        with pytest.raises(Exception) as exc:
            await transition(session, v, "tested", actor=None)
        assert "steps_not_confirmed" in str(exc.value)
        with pytest.raises(Exception) as exc:
            await transition(session, v, "published", actor=None)
        assert "illegal_transition" in str(exc.value)
        await session.rollback()
    # author cannot submit an untested version
    denied = await app_client.post(
        f"/api/v1/versions/{version['id']}/submit-review", json={"summary": "please"}, headers=headers
    )
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "illegal_transition"


async def test_review_and_publish_flow(app_client):
    admin, a_headers, project = await setup_project(app_client)  # alice is admin (first user)
    bob = await register(app_client, "bob@example.com")
    b = auth(bob["access_token"])
    await app_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "bob@example.com", "role": "editor"},
        headers=a_headers,
    )
    carol = await register(app_client, "carol@example.com")
    c = auth(carol["access_token"])
    await app_client.patch(f"/api/v1/admin/users/{carol['user']['id']}", json={"role": "reviewer"}, headers=a_headers)

    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, b, project, fake)
        await accepted_trial(app_client, b, version["id"], fake)
        assert (await app_client.get(f"/api/v1/versions/{version['id']}", headers=b)).json()["state"] == "tested"

        # publishing before review is refused (state machine); submit for review instead
        early = await app_client.post(
            f"/api/v1/versions/{version['id']}/authorize",
            json={
                "action": "publish",
                "checklist": {"reviewed_diff": True, "trial_accepted": True, "install_docs_checked": True},
            },
            headers=b,
        )
        assert early.status_code == 409
        submitted = await app_client.post(
            f"/api/v1/versions/{version['id']}/submit-review",
            json={"summary": "First version, tested on Hermes"},
            headers=b,
        )
        assert submitted.status_code == 201, submitted.text
        req = submitted.json()
        assert (
            req["state"] == "open"
            and req["checklist"]["steps_confirmed"] == 3
            and req["checklist"]["trials_accepted"] == 1
            and req["checklist"]["irreversible_steps"] == ["send"]
        )
        assert (await app_client.get(f"/api/v1/versions/{version['id']}", headers=b)).json()[
            "state"
        ] == "submitted_for_review"
        again = await app_client.post(f"/api/v1/versions/{version['id']}/submit-review", json={}, headers=b)
        assert again.status_code == 409
        # reviewers were notified; bob (author) was not
        notes = (await app_client.get("/api/v1/me/notifications", headers=c)).json()
        assert any(n["kind"] == "review_requested" for n in notes["items"])
        assert not any(
            n["kind"] == "review_requested"
            for n in (await app_client.get("/api/v1/me/notifications", headers=b)).json()["items"]
        )

        # queue visible to reviewers only
        assert (await app_client.get("/api/v1/review/queue", headers=b)).status_code == 403
        queue = (await app_client.get("/api/v1/review/queue", headers=c)).json()
        assert len(queue) == 1 and queue[0]["skill_name"] == "invoice-check" and queue[0]["requested_by_name"] == "bob"
        bundle = (await app_client.get(f"/api/v1/review/{req['id']}", headers=c)).json()
        assert bundle["previous_version"] is None and bundle["diff"]["steps"]["added"] == ["open-sheet", "flag", "send"]
        assert any(f["path"] == "SKILL.md" for f in bundle["files"])
        assigned = await app_client.post(f"/api/v1/review/{req['id']}/assign", headers=c)
        assert assigned.json()["state"] == "in_review" and assigned.json()["assignee_id"] == carol["user"]["id"]

        # self review blocked by default (bob is not a reviewer anyway -> 403)
        assert (
            await app_client.post(f"/api/v1/review/{req['id']}/decision", json={"decision": "approved"}, headers=b)
        ).status_code == 403
        changes = await app_client.post(
            f"/api/v1/review/{req['id']}/decision",
            json={
                "decision": "changes_requested",
                "comment": "Add an example to step flag",
                "file_comments": [{"path": "SKILL.md", "line": 10, "text": "unclear"}],
            },
            headers=c,
        )
        assert changes.status_code == 200 and changes.json()["decision"] == "changes_requested"
        assert (await app_client.get(f"/api/v1/versions/{version['id']}", headers=b)).json()[
            "state"
        ] == "changes_requested"
        assert any(
            n["kind"] == "review_decided"
            for n in (await app_client.get("/api/v1/me/notifications", headers=b)).json()["items"]
        )
        decided_twice = await app_client.post(
            f"/api/v1/review/{req['id']}/decision", json={"decision": "approved"}, headers=c
        )
        assert decided_twice.status_code == 409

        # author resubmits (same version after edits) and the reviewer approves
        resubmitted = await app_client.post(
            f"/api/v1/versions/{version['id']}/submit-review", json={"summary": "example added"}, headers=b
        )
        assert resubmitted.status_code == 201
        req2 = resubmitted.json()
        approved = await app_client.post(
            f"/api/v1/review/{req2['id']}/decision", json={"decision": "approved", "comment": "good"}, headers=c
        )
        assert approved.status_code == 200
        assert (await app_client.get(f"/api/v1/versions/{version['id']}", headers=b)).json()["state"] == "approved"
        transitions = (await app_client.get(f"/api/v1/versions/{version['id']}/transitions", headers=b)).json()
        assert [t["to_state"] for t in transitions] == [
            "testing",
            "tested",
            "submitted_for_review",
            "changes_requested",
            "submitted_for_review",
            "approved",
        ]
        assert (
            transitions[-1]["review_decision_id"] == approved.json()["id"]
            and transitions[-1]["actor_user_id"] == carol["user"]["id"]
        )

        # publish needs a human project editor with a complete checklist; viewers cannot
        dave = await register(app_client, "dave@example.com")
        d = auth(dave["access_token"])
        await app_client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"email": "dave@example.com", "role": "viewer"},
            headers=a_headers,
        )
        assert (
            await app_client.post(
                f"/api/v1/versions/{version['id']}/authorize",
                json={
                    "action": "publish",
                    "checklist": {"reviewed_diff": True, "trial_accepted": True, "install_docs_checked": True},
                },
                headers=d,
            )
        ).status_code == 403
        incomplete = await app_client.post(
            f"/api/v1/versions/{version['id']}/authorize",
            json={"action": "publish", "checklist": {"reviewed_diff": True}},
            headers=b,
        )
        assert incomplete.status_code == 422 and "trial_accepted" in incomplete.json()["error"]["details"]["missing"]
        published = await app_client.post(
            f"/api/v1/versions/{version['id']}/authorize",
            json={
                "action": "publish",
                "checklist": {"reviewed_diff": True, "trial_accepted": True, "install_docs_checked": True},
                "comment": "go live",
            },
            headers=b,
        )
        assert published.status_code == 200 and published.json()["decision"] == "granted"
        v = (await app_client.get(f"/api/v1/versions/{version['id']}", headers=b)).json()
        assert v["state"] == "published"
        skill = (await app_client.get(f"/api/v1/skills/{skill_id}", headers=b)).json()
        assert skill["current_published_version_id"] == version["id"]

        # second version: patch, trial, review, publish -> first becomes superseded; diff shows the change
        fake.script(Scripted(purpose="author", json={**sample_spec().model_dump(), "changelog": "v2"}))
        await app_client.post(
            f"/api/v1/skills/{skill_id}/versions/generate", json={"mode": "patch", "instructions": "x"}, headers=b
        )
        await get_job_runner().wait_all()
        v2 = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=b)).json()[0]
        assert v2["version"] == "0.1.1"
        await accepted_trial(app_client, b, v2["id"], fake)
        req3 = (await app_client.post(f"/api/v1/versions/{v2['id']}/submit-review", json={}, headers=b)).json()
        bundle = (await app_client.get(f"/api/v1/review/{req3['id']}", headers=c)).json()
        assert bundle["previous_version"] == "0.1.0" and bundle["diff"]["suggested_bump"] in ("patch", "minor")
        await app_client.post(f"/api/v1/review/{req3['id']}/decision", json={"decision": "approved"}, headers=c)
        await app_client.post(
            f"/api/v1/versions/{v2['id']}/authorize",
            json={
                "action": "publish",
                "checklist": {"reviewed_diff": True, "trial_accepted": True, "install_docs_checked": True},
            },
            headers=b,
        )
        states = {
            x["version"]: x["state"]
            for x in (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=b)).json()
        }
        assert states == {"0.1.1": "published", "0.1.0": "superseded"}
        diff = (await app_client.get(f"/api/v1/versions/{v2['id']}/diff", headers=b)).json()
        assert diff["from"] == "0.1.0" and diff["to"] == "0.1.1"

        # deprecate needs its own authorization
        dep = await app_client.post(
            f"/api/v1/versions/{v2['id']}/authorize",
            json={"action": "deprecate", "checklist": {"installers_notified": True}},
            headers=b,
        )
        assert dep.status_code == 200
        assert (await app_client.get(f"/api/v1/skills/{skill_id}", headers=b)).json()[
            "current_published_version_id"
        ] is None
        auths = (await app_client.get(f"/api/v1/versions/{v2['id']}/authorizations", headers=b)).json()
        assert [x["action"] for x in auths] == ["publish", "deprecate"]
    finally:
        set_fake_provider(None)


async def test_withdraw_and_self_review_setting(app_client):
    admin, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)
        await accepted_trial(app_client, headers, version["id"], fake)
        req = (
            await app_client.post(f"/api/v1/versions/{version['id']}/submit-review", json={}, headers=headers)
        ).json()
        # admin submitted it: self review refused until the setting allows it
        refused = await app_client.post(
            f"/api/v1/review/{req['id']}/decision", json={"decision": "approved"}, headers=headers
        )
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "self_review_not_allowed"
        withdrawn = await app_client.post(f"/api/v1/review/{req['id']}/withdraw", headers=headers)
        assert withdrawn.json()["state"] == "withdrawn"
        assert (await app_client.get(f"/api/v1/versions/{version['id']}", headers=headers)).json()["state"] == "tested"
        await app_client.put("/api/v1/admin/settings", json={"values": {"allow_self_review": True}}, headers=headers)
        req2 = (
            await app_client.post(f"/api/v1/versions/{version['id']}/submit-review", json={}, headers=headers)
        ).json()
        ok = await app_client.post(
            f"/api/v1/review/{req2['id']}/decision", json={"decision": "rejected", "comment": "no"}, headers=headers
        )
        assert ok.status_code == 200
        assert (await app_client.get(f"/api/v1/versions/{version['id']}", headers=headers)).json()[
            "state"
        ] == "rejected"
        mine = (await app_client.get("/api/v1/review/mine", headers=headers)).json()
        assert [m["state"] for m in mine] == ["decided", "withdrawn"]
    finally:
        set_fake_provider(None)
