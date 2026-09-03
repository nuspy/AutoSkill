"""Skill Hub: visibility, search, favorites, installations + update notifications, forks, git repo."""

import json
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


async def test_ratings_lists_contributions_promotion_and_mirror(app_client, monkeypatch):
    """Phase 8 hub features: star ratings, curated lists, contribute back from a variant, promotion of a hub
    skill to the component catalog, and mirroring a publish to an external git remote."""
    admin, a, project = await setup_project(app_client)
    bob = await register(app_client, "bob@example.com")
    b = auth(bob["access_token"])
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await publish_skill(app_client, a, project, fake)
        await app_client.patch(f"/api/v1/skills/{skill_id}/publish-settings", json={"visibility": "shared"}, headers=a)

        # --- ratings ---
        bad = await app_client.put(f"/api/v1/hub/skills/{skill_id}/rating", json={"stars": 6}, headers=b)
        assert bad.status_code == 422
        r1 = await app_client.put(
            f"/api/v1/hub/skills/{skill_id}/rating", json={"stars": 4, "comment": "Works well"}, headers=b
        )
        assert r1.status_code == 200 and r1.json()["user_name"] == "bob"
        await app_client.put(f"/api/v1/hub/skills/{skill_id}/rating", json={"stars": 2}, headers=a)
        detail = (await app_client.get(f"/api/v1/hub/skills/{skill_id}", headers=b)).json()
        assert detail["skill"]["rating_avg"] == 3.0 and detail["skill"]["rating_count"] == 2
        assert detail["my_rating"]["stars"] == 4 and len(detail["ratings"]) == 2
        # re-rating replaces, not duplicates; removing recomputes
        await app_client.put(f"/api/v1/hub/skills/{skill_id}/rating", json={"stars": 5}, headers=b)
        assert (await app_client.get(f"/api/v1/hub/skills/{skill_id}", headers=b)).json()["skill"]["rating_avg"] == 3.5
        await app_client.delete(f"/api/v1/hub/skills/{skill_id}/rating", headers=a)
        home = (await app_client.get("/api/v1/hub", headers=b)).json()
        assert home["top_rated"][0]["id"] == skill_id and home["top_rated"][0]["rating_count"] == 1
        search = (await app_client.get("/api/v1/hub/search?sort=rating", headers=b)).json()
        assert search["items"][0]["id"] == skill_id

        # --- curated lists ---
        lst = await app_client.post(
            "/api/v1/admin/hub/lists",
            json={"slug": "starters", "name": {"en": "Starters", "it": "Per iniziare"}},
            headers=a,
        )
        assert lst.status_code == 201, lst.text
        assert (
            await app_client.post("/api/v1/admin/hub/lists", json={"slug": "starters", "name": {"en": "x"}}, headers=a)
        ).status_code == 409
        added = await app_client.post(f"/api/v1/admin/hub/lists/{lst.json()['id']}/items/{skill_id}", headers=a)
        assert added.status_code == 200 and [s["id"] for s in added.json()["items"]] == [skill_id]
        assert (
            await app_client.post("/api/v1/admin/hub/lists", json={"slug": "x", "name": {}}, headers=b)
        ).status_code == 403
        home = (await app_client.get("/api/v1/hub", headers=b)).json()
        assert home["lists"][0]["slug"] == "starters" and home["lists"][0]["count"] == 1
        one = (await app_client.get("/api/v1/hub/lists/starters", headers=b)).json()
        assert one["list"]["name"]["it"] == "Per iniziare" and one["items"][0]["id"] == skill_id
        assert (await app_client.get("/api/v1/hub/lists/nope", headers=b)).status_code == 404
        removed = await app_client.delete(f"/api/v1/admin/hub/lists/{lst.json()['id']}/items/{skill_id}", headers=a)
        assert removed.json()["items"] == []

        # --- contribute back: bob forks, tests and proposes; alice accepts -> draft on the original ---
        bobs_project = (await app_client.post("/api/v1/projects", json={"name": "Bob"}, headers=b)).json()
        fork = (
            await app_client.post(
                f"/api/v1/skills/{skill_id}/fork", json={"target_project_id": bobs_project["id"]}, headers=b
            )
        ).json()
        fv = (await app_client.get(f"/api/v1/skills/{fork['id']}/versions", headers=b)).json()[0]
        early = await app_client.post(f"/api/v1/skills/{fork['id']}/contribute", json={}, headers=b)
        assert early.status_code == 409 and early.json()["error"]["code"] == "version_not_contributable"
        await accepted_trial(app_client, b, fv["id"], fake)
        not_fork = await app_client.post(f"/api/v1/skills/{skill_id}/contribute", json={}, headers=a)
        assert not_fork.status_code == 422
        contrib = await app_client.post(
            f"/api/v1/skills/{fork['id']}/contribute", json={"message": "I fixed the month sheet"}, headers=b
        )
        assert contrib.status_code == 201, contrib.text
        contrib = contrib.json()
        assert (
            contrib["state"] == "open"
            and contrib["target_skill_id"] == skill_id
            and contrib["proposed_by_name"] == "bob"
        )
        assert (await app_client.post(f"/api/v1/skills/{fork['id']}/contribute", json={}, headers=b)).status_code == 409
        notes = (await app_client.get("/api/v1/me/notifications", headers=a)).json()["items"]
        assert any(n["kind"] == "contribution_received" for n in notes)
        listed = (await app_client.get(f"/api/v1/skills/{skill_id}/contributions", headers=a)).json()
        assert [c["id"] for c in listed] == [contrib["id"]] and listed[0]["source_title"] == fork["title"]
        assert (
            await app_client.post(f"/api/v1/contributions/{contrib['id']}/decision", json={"accept": True}, headers=b)
        ).status_code == 403
        decided = await app_client.post(
            f"/api/v1/contributions/{contrib['id']}/decision", json={"accept": True, "comment": "thanks"}, headers=a
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["state"] == "accepted" and decided.json()["target_version_id"]
        versions = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=a)).json()
        newest = versions[0]
        assert newest["id"] == decided.json()["target_version_id"] and newest["state"] == "draft"
        assert newest["origin"] == "contribution" and newest["version"] == "0.1.1"
        md = (await app_client.get(f"/api/v1/versions/{newest['id']}/files/SKILL.md", headers=a)).json()["content"]
        assert "name: invoice-check\n" in md and "contributed_from:" in md
        assert (
            await app_client.post(f"/api/v1/contributions/{contrib['id']}/decision", json={"accept": False}, headers=a)
        ).status_code == 409
        assert any(
            n["kind"] == "contribution_decided"
            for n in (await app_client.get("/api/v1/me/notifications", headers=b)).json()["items"]
        )

        # --- promote the published skill to the component catalog ---
        promoted = await app_client.post(f"/api/v1/library/from-skill/{skill_id}", headers=a)
        assert promoted.status_code == 201, promoted.text
        comp = promoted.json()
        assert comp["kind"] == "skill" and comp["slug"] == "invoice-check" and comp["source"]["type"] == "hub_skill"
        assert comp["artifact"]["filename"] == "invoice-check.zip" and comp["version"] == version["version"]
        again = await app_client.post(f"/api/v1/library/from-skill/{skill_id}", headers=a)
        assert again.status_code == 201 and again.json()["id"] == comp["id"]
        assert (await app_client.post(f"/api/v1/library/from-skill/{fork['id']}", headers=a)).status_code == 409
        assert (await app_client.post(f"/api/v1/library/from-skill/{skill_id}", headers=b)).status_code == 403

        # --- external mirror: configured through publish settings, pushed by the job after a publish ---
        if git_repo.git_available():
            remote = Path(tempfile.mkdtemp(prefix="autoskill-mirror-"))
            subprocess.run(["git", "init", "--bare", "--quiet", "--initial-branch=main", str(remote)], check=True)
            bad = await app_client.patch(
                f"/api/v1/skills/{skill_id}/publish-settings", json={"external_remote_url": "ftp://x"}, headers=a
            )
            assert bad.status_code == 422
            ok = await app_client.patch(
                f"/api/v1/skills/{skill_id}/publish-settings",
                json={"external_remote_url": f"file://{remote}", "external_token": "secret-token"},
                headers=a,
            )
            assert ok.status_code == 200
            status = (await app_client.get(f"/api/v1/skills/{skill_id}/mirror", headers=a)).json()
            assert status["external_remote_url"] == f"file://{remote}" and status["has_token"] is True
            assert "secret-token" not in json.dumps(status)
            # publish the accepted contribution draft (trial -> review -> authorize) and expect the mirror push
            await accepted_trial(app_client, a, newest["id"], fake)
            req = (await app_client.post(f"/api/v1/versions/{newest['id']}/submit-review", json={}, headers=a)).json()
            await app_client.post(f"/api/v1/review/{req['id']}/decision", json={"decision": "approved"}, headers=a)
            pub = await app_client.post(
                f"/api/v1/versions/{newest['id']}/authorize",
                json={"action": "publish", "checklist": CHECKLIST},
                headers=a,
            )
            assert pub.status_code == 200, pub.text
            await get_job_runner().wait_all()
            status = (await app_client.get(f"/api/v1/skills/{skill_id}/mirror", headers=a)).json()
            assert status["last_external_error"] is None and status["last_external_push_at"], status
            tags = subprocess.run(["git", "tag", "--list"], cwd=remote, capture_output=True, text=True).stdout.split()
            assert "v0.1.1" in tags
            tree = subprocess.run(
                ["git", "ls-tree", "--name-only", "main"], cwd=remote, capture_output=True, text=True
            ).stdout
            assert "SKILL.md" in tree and "autoskill.json" in tree
    finally:
        set_fake_provider(None)
