"""Install bundles: INSTALL.md / install.json / artifacts reachable online without login (download grants),
public hub bundles, library component artifacts, agent-usable URLs for every cited component."""

import hashlib
import io
import json
import zipfile

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from autoskill.schemas.draft import DraftDependency
from tests.test_drafting import run_interview_to_completion
from tests.test_interview import setup_project
from tests.test_packaging import sample_spec

PUBLIC = "http://localhost:8000"


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


MCP_ZIP = _zip(
    {
        "pyproject.toml": '[project]\nname = "email-mcp"\nversion = "1.0.0"\n[project.scripts]\nemail-mcp = "email_mcp:main"\n',
        "email_mcp/__init__.py": "def main():\n    pass\n",
    }
)
SKILL_ZIP = _zip(
    {"ldap-notes/SKILL.md": "---\nname: ldap-notes\ndescription: Look up people in the directory.\n---\n\nBody.\n"}
)


async def _component(app_client, headers, **body):
    base = {"version": "1.0.0", "tools": [], "env_requirements": [], "install": {}, "tags": []}
    res = await app_client.post("/api/v1/library", json={**base, **body}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _upload(app_client, headers, component_id: str, filename: str, data: bytes):
    return await app_client.post(
        f"/api/v1/library/{component_id}/artifact",
        files={"file": (filename, data, "application/zip")},
        headers=headers,
    )


async def _draft_with_dependencies(app_client, headers, project, fake, slugs):
    sid = await run_interview_to_completion(app_client, headers, project, fake)
    spec = sample_spec()
    spec.dependencies = [DraftDependency(component_slug=s, reason=f"uses {s}") for s in slugs]
    fake.script(Scripted(purpose="author", json=spec.model_dump()))
    await app_client.post(f"/api/v1/interviews/{sid}/confirm", json={"confirmed": True}, headers=headers)
    await get_job_runner().wait_all()
    skill_id = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()["session"]["skill_id"]
    version = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)).json()[0]
    return skill_id, version


def _path(url: str) -> str:
    assert url.startswith(PUBLIC + "/"), url
    return url[len(PUBLIC) :]


async def test_library_artifacts_are_validated(app_client):
    _user, a, _project = await setup_project(app_client)
    mcp = await _component(
        app_client,
        a,
        kind="mcp_server",
        slug="email-mcp",
        name="Email MCP",
        description="Send and read email.",
        install={"command": "email-mcp", "args": ["--stdio"]},
        env_requirements=[{"name": "SMTP_PASSWORD", "description": "smtp password", "secret": True}],
    )
    bad = await _upload(app_client, a, mcp["id"], "email-mcp.zip", _zip({"readme.txt": "no project here"}))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "artifact_not_installable"
    ok = await _upload(app_client, a, mcp["id"], "email-mcp.zip", MCP_ZIP)
    assert ok.status_code == 200, ok.text
    art = ok.json()["artifact"]
    assert art["sha256"] == hashlib.sha256(MCP_ZIP).hexdigest() and art["size"] == len(MCP_ZIP)
    assert ok.json()["source"]["type"] == "package_upload"

    skill = await _component(
        app_client, a, kind="skill", slug="ldap-notes", name="LDAP notes", description="Directory lookups."
    )
    wrong_name = await _upload(
        app_client, a, skill["id"], "x.zip", _zip({"other/SKILL.md": "---\nname: other\ndescription: d\n---\nb"})
    )
    assert wrong_name.status_code == 422 and wrong_name.json()["error"]["code"] == "artifact_name_mismatch"
    assert (await _upload(app_client, a, skill["id"], "ldap-notes.zip", SKILL_ZIP)).status_code == 200
    # authenticated download and delete
    dl = await app_client.get(f"/api/v1/library/{skill['id']}/artifact", headers=a)
    assert dl.status_code == 200 and dl.content == SKILL_ZIP
    gone = await app_client.delete(f"/api/v1/library/{skill['id']}/artifact", headers=a)
    assert gone.status_code == 200 and gone.json()["artifact"] is None


async def test_trial_bundle_reachable_without_login_with_every_component(app_client):
    _user, a, project = await setup_project(app_client)
    mcp = await _component(
        app_client,
        a,
        kind="mcp_server",
        slug="email-mcp",
        name="Email MCP",
        description="Send and read email.",
        install={"command": "email-mcp", "args": ["--stdio"]},
        env_requirements=[{"name": "SMTP_PASSWORD", "description": "smtp password", "secret": True}],
        docs="Configure the SMTP account first.",
    )
    assert (await _upload(app_client, a, mcp["id"], "email-mcp.zip", MCP_ZIP)).status_code == 200
    notes = await _component(
        app_client, a, kind="skill", slug="ldap-notes", name="LDAP notes", description="Directory lookups."
    )
    assert (await _upload(app_client, a, notes["id"], "ldap-notes.zip", SKILL_ZIP)).status_code == 200
    other = await _component(app_client, a, kind="mcp_server", slug="other", name="Other", description="unused")
    assert (await _upload(app_client, a, other["id"], "other.zip", MCP_ZIP)).status_code == 200

    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await _draft_with_dependencies(app_client, a, project, fake, ["email-mcp", "ldap-notes"])
        created = await app_client.post(
            "/api/v1/trials",
            json={"skill_version_id": version["id"], "target_agent": "openclaw", "purpose": "develop"},
            headers=a,
        )
    finally:
        set_fake_provider(None)
    assert created.status_code == 201, created.text
    trial = created.json()
    assert trial["bundle_url"].startswith(PUBLIC + "/dl/") and trial["manifest_url"].endswith("/install.json")
    assert trial["cli_command"] == (
        f"autoskill trial install --from {trial['manifest_url']} --target openclaw --token {trial['session_token']}"
    )

    # --- the agent fetches the manifest with no credentials at all ---
    res = await app_client.get(_path(trial["manifest_url"]))
    assert res.status_code == 200, res.text
    manifest = res.json()
    assert manifest["format"] == "autoskill-install/1" and manifest["kind"] == "trial"
    assert manifest["default_target"] == "openclaw" and manifest["trial"]["session_id"] == trial["id"]
    assert manifest["trial"]["installed_callback_url"] == f"{PUBLIC}/api/v1/trials/{trial['id']}/installed"
    names = {m["name"]: m for m in manifest["mcp_servers"]}
    assert set(names) == {"autoskill-companion", "email-mcp"}
    email = names["email-mcp"]
    assert email["kind"] == "library" and email["install"]["method"] == "pipx_archive"
    assert email["download"]["sha256"] == hashlib.sha256(MCP_ZIP).hexdigest()
    assert email["install"]["command"] == f"pipx install {email['download']['url']}"
    assert email["registration"] == {
        "command": "email-mcp",
        "args": ["--stdio"],
        "url": None,
        "env_requirements": [{"name": "SMTP_PASSWORD", "description": "smtp password", "secret": True}],
    }
    assert "mcp_servers:" in email["snippets"]["hermes"] and "mcpServers" in email["snippets"]["openclaw"]
    assert email["docs"] == "Configure the SMTP account first."
    (comp,) = manifest["components"]
    assert comp["slug"] == "ldap-notes" and comp["install"]["method"] == "copy" and comp["reason"] == "uses ldap-notes"
    assert comp["install_paths"]["hermes"] == "~/.hermes/skills/ldap-notes"
    assert manifest["skill"]["install_paths"]["openclaw"][0] == "~/.openclaw/skills/invoice-check/"
    assert any(
        env["name"] == "AUTOSKILL_SESSION_TOKEN"
        for env in names["autoskill-companion"]["registration"]["env_requirements"]
    )
    assert manifest["agent_instructions"] and "trial callback" in manifest["agent_instructions"][-1]

    # --- every URL cited in the manifest works with the same token and matches its checksum ---
    urls = [manifest["skill"]["download"]["url"], email["download"]["url"], comp["download"]["url"]]
    urls += list(manifest["install_md_urls"].values()) + [manifest["bundle_url"]]
    for url in urls:
        r = await app_client.get(_path(url))
        assert r.status_code == 200, (url, r.status_code)
    assert (
        hashlib.sha256((await app_client.get(_path(email["download"]["url"]))).content).hexdigest()
        == email["download"]["sha256"]
    )
    assert (await app_client.get(_path(comp["download"]["url"]))).content == SKILL_ZIP
    skill_zip = (await app_client.get(_path(manifest["skill"]["download"]["url"]))).content
    with zipfile.ZipFile(io.BytesIO(skill_zip)) as zf:
        entries = set(zf.namelist())
        skill_md = zf.read("invoice-check/SKILL.md").decode()
        embedded = json.loads(zf.read("invoice-check/autoskill.json"))
    assert {
        "invoice-check/INSTALL.openclaw.md",
        "invoice-check/INSTALL.hermes.md",
        "invoice-check/autoskill.json",
    } <= entries
    assert f"autoskill_trial: {trial['id']}" in skill_md
    assert embedded["skill"]["download"]["url"] == manifest["skill"]["download"]["url"]

    md = await app_client.get(_path(trial["bundle_url"]))
    assert md.headers["content-type"].startswith("text/markdown")
    text = md.text
    assert "on OpenClaw" in text and "## Download links" in text and manifest["manifest_url"] in text
    assert "Email MCP" in text and email["download"]["url"] in text and "LDAP notes" in text
    assert "## For AI agents" in text and "X-AutoSkill-Trial" in text
    assert f"autoskill trial install --from {manifest['manifest_url']} --target openclaw" in text
    hermes = (await app_client.get(_path(manifest["install_md_urls"]["hermes"]))).text
    assert "~/.hermes/skills/invoice-check/" in hermes and "SMTP_PASSWORD: <SMTP_PASSWORD>" in hermes

    # --- only what the version declares is served; bad paths and tokens fail closed ---
    base = trial["manifest_url"].rsplit("/", 1)[0]
    assert (await app_client.get(_path(f"{base}/components/other/other.zip"))).status_code == 404
    assert (await app_client.get(_path(f"{base}/components/ldap-notes/wrong.zip"))).status_code == 404
    assert (await app_client.get(_path(f"{base}/INSTALL.emacs.md"))).status_code == 404
    assert (await app_client.get(_path(f"{base}/mcp/invoice-check-tools.zip"))).status_code == 404  # none generated
    assert (await app_client.get("/dl/nope-not-a-token/install.json")).status_code == 404
    # the same address is shown again in the trial page and the install guide
    detail = (await app_client.get(f"/api/v1/trials/{trial['id']}", headers=a)).json()
    assert detail["bundle_url"] == trial["bundle_url"] and detail["manifest_url"] == trial["manifest_url"]
    guide = (await app_client.get(f"/api/v1/trials/{trial['id']}/install/hermes", headers=a)).json()
    assert guide["bundle_url"] == manifest["install_md_urls"]["hermes"]
    # the agent reports the installation with the trial token alone
    inst = await app_client.post(
        f"/api/v1/trials/{trial['id']}/installed",
        json={"install_manifest": {"target": "openclaw", "manual": True}, "build": 1},
        headers={"X-AutoSkill-Trial": trial["session_token"]},
    )
    assert inst.status_code == 200 and inst.json()["state"] == "installed"
    # closing the trial invalidates the link
    assert (await app_client.delete(f"/api/v1/trials/{trial['id']}", headers=a)).status_code == 200
    gone = await app_client.get(_path(trial["manifest_url"]))
    assert gone.status_code == 410 and gone.json()["error"]["code"] == "link_expired"


async def test_version_download_links_and_public_hub_bundle(app_client):
    from tests.test_hub import publish_skill

    _user, a, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await publish_skill(app_client, a, project, fake)
    finally:
        set_fake_provider(None)

    # private skill: the install guide only has hub URLs (not reachable) until a link is created
    guide = (await app_client.get(f"/api/v1/versions/{version['id']}/install/hermes", headers=a)).json()
    assert guide["public"] is True and "/dl/hub/" in guide["bundle_url"]
    assert (await app_client.get(_path(guide["manifest_url"]))).status_code == 404

    link = await app_client.post(
        f"/api/v1/versions/{version['id']}/download-links",
        json={"expires_in_days": 7, "label": "for my agent", "target_agent": "codex"},
        headers=a,
    )
    assert link.status_code == 201, link.text
    link = link.json()
    assert link["kind"] == "version" and link["expires_at"] and link["label"] == "for my agent"
    listed = (await app_client.get(f"/api/v1/versions/{version['id']}/download-links", headers=a)).json()
    assert [x["id"] for x in listed] == [link["id"]] and listed[0]["bundle_url"] == link["bundle_url"]
    manifest = (await app_client.get(_path(link["manifest_url"]))).json()
    assert manifest["kind"] == "version" and manifest["expires_at"] and manifest["default_target"] == "codex"
    assert manifest["skill"]["git_url"] == f"{PUBLIC}/git/{project['slug']}/invoice-check.git"
    assert manifest["trial"] is None
    md = (await app_client.get(_path(link["bundle_url"]))).text
    assert "on OpenAI Codex" in md and f"autoskill install --from {link['manifest_url']} --target codex" in md
    zip_res = await app_client.get(_path(manifest["skill"]["download"]["url"]))
    assert zip_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
        assert "autoskill_trial" not in zf.read("invoice-check/SKILL.md").decode()
    # the guide now points at the link, and a stranger cannot revoke it
    guide = (await app_client.get(f"/api/v1/versions/{version['id']}/install/codex", headers=a)).json()
    assert guide["public"] is False and guide["manifest_url"] == link["manifest_url"]
    from tests.conftest import auth, register

    bob = auth((await register(app_client, "bob@example.com"))["access_token"])
    assert (await app_client.delete(f"/api/v1/download-links/{link['id']}", headers=bob)).status_code in (403, 404)
    revoked = await app_client.delete(f"/api/v1/download-links/{link['id']}", headers=a)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"]
    assert (await app_client.get(_path(link["manifest_url"]))).status_code == 410

    # public skill on a public hub: stable address, no token
    hub_base = f"/dl/hub/{project['slug']}/invoice-check"
    assert (await app_client.get(f"{hub_base}/latest/install.json")).status_code == 404
    await app_client.put("/api/v1/admin/settings", json={"values": {"public_hub": True}}, headers=a)
    await app_client.patch(f"/api/v1/skills/{skill_id}/publish-settings", json={"visibility": "public"}, headers=a)
    latest = await app_client.get(f"{hub_base}/latest/install.json")
    assert latest.status_code == 200, latest.text
    manifest = latest.json()
    assert manifest["kind"] == "hub" and manifest["skill"]["download"]["url"] == f"{PUBLIC}{hub_base}/0.1.0/skill.zip"
    assert (await app_client.get(f"{hub_base}/0.1.0/INSTALL.hermes.md")).status_code == 200
    assert (await app_client.get(f"{hub_base}/0.1.0/skill.zip")).status_code == 200
    assert (await app_client.get(f"{hub_base}/9.9.9/install.json")).status_code == 404
    # wheel endpoint: nothing published on this test server
    assert (await app_client.get("/dl/autoskill-local/latest")).status_code == 404


async def test_download_rate_limit_and_link_cap(app_client):
    from autoskill.core.ratelimit import MemoryRateLimiter, RateLimited, get_rate_limiter

    _user, a, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        _skill_id, version = await _draft_with_dependencies(app_client, a, project, fake, [])
    finally:
        set_fake_provider(None)
    await app_client.put(
        "/api/v1/admin/settings",
        json={"values": {"max_active_download_links_per_user": 2, "download_rate_per_minute": 5}},
        headers=a,
    )
    links = []
    for _ in range(2):
        r = await app_client.post(f"/api/v1/versions/{version['id']}/download-links", json={}, headers=a)
        assert r.status_code == 201, r.text
        links.append(r.json())
    capped = await app_client.post(f"/api/v1/versions/{version['id']}/download-links", json={}, headers=a)
    assert capped.status_code == 409 and capped.json()["error"]["code"] == "too_many_links"
    await app_client.delete(f"/api/v1/download-links/{links[0]['id']}", headers=a)
    assert (
        await app_client.post(f"/api/v1/versions/{version['id']}/download-links", json={}, headers=a)
    ).status_code == 201

    # the same token may be used 5 times per minute, then 429 (memory backend in tests)
    path = _path(links[1]["manifest_url"])
    codes = [(await app_client.get(path)).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    assert isinstance(get_rate_limiter(), MemoryRateLimiter)
    limiter = MemoryRateLimiter()
    for _ in range(3):
        await limiter.hit("k", 3)
    import pytest

    with pytest.raises(RateLimited):
        await limiter.hit("k", 3)
    await limiter.hit("other", 3)  # independent keys
