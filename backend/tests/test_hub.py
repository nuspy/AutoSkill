"""Skill Hub: visibility, search, favorites, installations + update notifications, forks, git repo."""

import subprocess
import tempfile
from pathlib import Path

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider
from autoskill.llm.registry import set_fake_provider
from autoskill.services.distribution import git_repo
from tests.conftest import auth, register
from tests.test_interview import setup_project
from tests.test_review import accepted_trial
from tests.test_trials import make_draft

CHECKLIST = {"reviewed_diff": True, "trial_accepted": True, "install_docs_checked": True}


async def publish_skill(app_client, admin_headers, project, fake, title="Invoice check"):
    """Draft -> trial -> review (admin self-review allowed) -> publish. Returns (skill_id, version)."""
    await app_client.put("/api/v1/admin/settings", json={"values": {"allow_self_review": True}}, headers=admin_headers)
    skill_id, version = await make_draft(app_client, admin_headers, project, fake)
    await accepted_trial(app_client, admin_headers, version["id"], fake)
    req = (
        await app_client.post(f"/api/v1/versions/{version['id']}/submit-review", json={}, headers=admin_headers)
    ).json()
    await app_client.post(f"/api/v1/review/{req['id']}/decision", json={"decision": "approved"}, headers=admin_headers)
    pub = await app_client.post(
        f"/api/v1/versions/{version['id']}/authorize",
        json={"action": "publish", "checklist": CHECKLIST},
        headers=admin_headers,
    )
    assert pub.status_code == 200, pub.text
    return skill_id, version


async def test_hub_visibility_search_favorites_and_installs(app_client):
    admin, a, project = await setup_project(app_client)
    bob = await register(app_client, "bob@example.com")
    b = auth(bob["access_token"])
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await publish_skill(app_client, a, project, fake)
    finally:
        set_fake_provider(None)

    # private by default: bob sees nothing in the hub and cannot open the skill
    home = (await app_client.get("/api/v1/hub", headers=b)).json()
    assert home["latest"] == [] and home["public"] is False
    assert (await app_client.get(f"/api/v1/hub/skills/{skill_id}", headers=b)).status_code == 404
    # anonymous hub is closed unless public_hub
    assert (await app_client.get("/api/v1/hub")).status_code == 403

    cat = (
        await app_client.post(
            "/api/v1/admin/hub/categories",
            json={"slug": "finance", "name": {"en": "Finance", "it": "Finanza"}},
            headers=a,
        )
    ).json()
    shared = await app_client.patch(
        f"/api/v1/skills/{skill_id}/publish-settings",
        json={"visibility": "shared", "category_id": cat["id"], "tags": ["Invoices", " monday "]},
        headers=a,
    )
    assert shared.status_code == 200 and shared.json()["tags"] == ["invoices", "monday"]
    home = (await app_client.get("/api/v1/hub", headers=b)).json()
    assert [s["name"] for s in home["latest"]] == ["invoice-check"]
    assert home["latest"][0]["published_version"] == "0.1.0" and home["latest"][0]["category_slug"] == "finance"
    assert home["categories"][0]["count"] == 1
    found = (await app_client.get("/api/v1/hub/search?q=invoice", headers=b)).json()
    assert found["total"] == 1
    assert (await app_client.get("/api/v1/hub/search?q=zzz", headers=b)).json()["total"] == 0
    assert (await app_client.get("/api/v1/hub/search?category=finance", headers=b)).json()["total"] == 1
    assert (await app_client.get("/api/v1/hub/search?tag=monday", headers=b)).json()["total"] == 1

    detail = (await app_client.get(f"/api/v1/hub/skills/{skill_id}", headers=b)).json()
    assert detail["skill"]["published_version_id"] == version["id"] and "## Steps" in detail["readme"]
    assert detail["versions"][0]["state"] == "published" and detail["my_installation"] is None
    assert detail["zip_url"].endswith(f"/versions/{version['id']}/package.zip")

    # favorites
    assert (await app_client.post(f"/api/v1/me/favorites/{skill_id}", headers=b)).status_code == 200
    assert (await app_client.get("/api/v1/me/favorites", headers=b)).json()[0]["is_favorite"] is True
    assert (await app_client.delete(f"/api/v1/me/favorites/{skill_id}", headers=b)).status_code == 200
    assert (await app_client.get("/api/v1/me/favorites", headers=b)).json() == []

    # download counts as an installation (downloaded) for bob on hermes; CLI registration confirms
    zip_res = await app_client.get(f"/api/v1/versions/{version['id']}/package.zip?target=hermes", headers=b)
    assert zip_res.status_code == 200
    installs = (await app_client.get("/api/v1/me/installations", headers=b)).json()
    assert len(installs) == 1 and installs[0]["state"] == "downloaded" and installs[0]["update_available"] is False
    reg = await app_client.post(
        "/api/v1/me/installations",
        json={"skill_version_id": version["id"], "target_agent": "hermes", "channel": "cli", "state": "installed"},
        headers=b,
    )
    assert reg.status_code == 201 and reg.json()["state"] == "installed"
    assert len((await app_client.get("/api/v1/me/installations", headers=b)).json()) == 1
    assert (await app_client.get(f"/api/v1/hub/skills/{skill_id}", headers=b)).json()["skill"]["install_count"] == 1

    # bob's device key + first production run confirm the installation
    start = await app_client.post(
        "/api/v1/auth/device", json={"device_name": "bob-laptop", "agent_targets": ["hermes"]}
    )
    await app_client.post("/api/v1/auth/device/confirm", json={"user_code": start.json()["user_code"]}, headers=b)
    key = (
        await app_client.post("/api/v1/auth/device/token", json={"device_code": start.json()["device_code"]})
    ).json()["api_key"]
    run = await app_client.post(
        "/api/v1/telemetry/runs", json={"skill_name": "invoice-check", "skill_version": "0.1.0"}, headers=auth(key)
    )
    assert run.status_code == 200, run.text
    inst = (await app_client.get("/api/v1/me/installations", headers=b)).json()[0]
    assert inst["state"] == "confirmed" and inst["run_count"] == 1

    # a new published version notifies bob and flags the update
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        from autoskill.llm.fake import Scripted
        from tests.test_packaging import sample_spec

        fake.script(Scripted(purpose="author", json={**sample_spec().model_dump(), "changelog": "v2 faster"}))
        await app_client.post(f"/api/v1/skills/{skill_id}/versions/generate", json={"mode": "patch"}, headers=a)
        await get_job_runner().wait_all()
        v2 = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=a)).json()[0]
        await accepted_trial(app_client, a, v2["id"], fake)
        req = (await app_client.post(f"/api/v1/versions/{v2['id']}/submit-review", json={}, headers=a)).json()
        await app_client.post(f"/api/v1/review/{req['id']}/decision", json={"decision": "approved"}, headers=a)
        assert (
            await app_client.post(
                f"/api/v1/versions/{v2['id']}/authorize", json={"action": "publish", "checklist": CHECKLIST}, headers=a
            )
        ).status_code == 200
    finally:
        set_fake_provider(None)
    inst = (await app_client.get("/api/v1/me/installations", headers=b)).json()[0]
    assert inst["update_available"] is True and inst["latest_version"] == "0.1.1"
    notes = (await app_client.get("/api/v1/me/notifications", headers=b)).json()["items"]
    assert any(n["kind"] == "skill_update_available" and "0.1.1" in n["title"] for n in notes)

    # feature + admin listing + public hub
    assert (await app_client.post(f"/api/v1/admin/hub/skills/{skill_id}/feature", headers=a)).json()[
        "visibility"
    ] == "shared"
    assert (await app_client.get("/api/v1/hub", headers=b)).json()["featured"][0]["id"] == skill_id
    assert len((await app_client.get("/api/v1/admin/hub/skills", headers=a)).json()) == 1
    await app_client.put("/api/v1/admin/settings", json={"values": {"public_hub": True}}, headers=a)
    await app_client.patch(f"/api/v1/skills/{skill_id}/publish-settings", json={"visibility": "public"}, headers=a)
    anon = await app_client.get("/api/v1/hub")
    assert (
        anon.status_code == 200
        and anon.json()["public"] is True
        and anon.json()["latest"][0]["name"] == "invoice-check"
    )
    assert (await app_client.get(f"/api/v1/hub/skills/{skill_id}")).status_code == 200
    assert (await app_client.delete(f"/api/v1/me/installations/{inst['id']}", headers=b)).status_code == 200
    assert (await app_client.get("/api/v1/me/installations", headers=b)).json() == []


async def test_fork_creates_personal_variant(app_client):
    admin, a, project = await setup_project(app_client)
    bob = await register(app_client, "bob@example.com")
    b = auth(bob["access_token"])
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await publish_skill(app_client, a, project, fake)
    finally:
        set_fake_provider(None)
    await app_client.patch(f"/api/v1/skills/{skill_id}/publish-settings", json={"visibility": "shared"}, headers=a)
    bobs_project = (await app_client.post("/api/v1/projects", json={"name": "Bob ops"}, headers=b)).json()
    forked = await app_client.post(
        f"/api/v1/skills/{skill_id}/fork",
        json={"target_project_id": bobs_project["id"], "title": "Invoice check (Bob)"},
        headers=b,
    )
    assert forked.status_code == 201, forked.text
    fs = forked.json()
    assert fs["project_id"] == bobs_project["id"] and fs["name"] == "invoice-check" and fs["visibility"] == "private"
    versions = (await app_client.get(f"/api/v1/skills/{fs['id']}/versions", headers=b)).json()
    assert (
        len(versions) == 1
        and versions[0]["version"] == "0.1.0"
        and versions[0]["origin"] == "fork"
        and versions[0]["state"] == "draft"
    )
    vd = (await app_client.get(f"/api/v1/versions/{versions[0]['id']}", headers=b)).json()
    assert [s["key"] for s in vd["steps"]] == ["open-sheet", "flag", "send"]
    md = (await app_client.get(f"/api/v1/versions/{versions[0]['id']}/files/SKILL.md", headers=b)).json()["content"]
    assert "forked_from: invoice-check@0.1.0" in md and "name: invoice-check" in md
    memory = (await app_client.get(f"/api/v1/skills/{fs['id']}/memory", headers=b)).json()
    assert any(m["kind"] == "decision" and "Forked" in m["title"] for m in memory)
    # bob cannot fork into a project he does not edit
    denied = await app_client.post(
        f"/api/v1/skills/{skill_id}/fork", json={"target_project_id": project["id"]}, headers=b
    )
    assert denied.status_code == 403


async def test_git_repo_publish_and_smart_http(app_client, monkeypatch):
    if not git_repo.git_available():
        return
    admin, a, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await publish_skill(app_client, a, project, fake)
    finally:
        set_fake_provider(None)
    bare = git_repo.repo_path(project["slug"], "invoice-check")
    assert bare.exists(), "publishing should create the bare repository"
    assert git_repo.list_tags(bare) == ["v0.1.0"]
    # a plain git clone of the bare repo has SKILL.md at the root and the install docs
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "clone", "-q", str(bare), tmp + "/c"], check=True, capture_output=True)
        assert (
            (Path(tmp) / "c" / "SKILL.md").exists()
            and (Path(tmp) / "c" / "INSTALL.openclaw.md").exists()
            and (Path(tmp) / "c" / "autoskill.json").exists()
        )
    # smart HTTP advertisement over the API (authenticated), read-only
    refs = await app_client.get(
        f"/git/{project['slug']}/invoice-check.git/info/refs?service=git-upload-pack", headers=a
    )
    assert (
        refs.status_code == 200 and b"# service=git-upload-pack" in refs.content and b"refs/tags/v0.1.0" in refs.content
    )
    assert (
        await app_client.get(f"/git/{project['slug']}/invoice-check.git/info/refs?service=git-upload-pack")
    ).status_code == 401
    assert (
        await app_client.post(f"/git/{project['slug']}/invoice-check.git/git-receive-pack", headers=a)
    ).status_code == 403
    detail = (await app_client.get(f"/api/v1/hub/skills/{skill_id}", headers=a)).json()
    assert detail["git_url"].endswith(f"/git/{project['slug']}/invoice-check.git")
