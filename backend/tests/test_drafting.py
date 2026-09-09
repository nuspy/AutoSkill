import io
import zipfile

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from tests.conftest import auth, register
from tests.test_interview import filled_doc, setup_project
from tests.test_packaging import sample_spec


async def run_interview_to_completion(app_client, headers, project, fake, title="Invoice check"):
    fake.script(
        Scripted(purpose="interviewer", json=filled_doc()),  # intake: everything but G8
        Scripted(purpose="interviewer", text="Summary."),
    )
    created = await app_client.post(
        f"/api/v1/projects/{project['id']}/interviews",
        json={"title": title, "description": "desc", "language": "en"},
        headers=headers,
    )
    sid = created.json()["id"]
    await get_job_runner().wait_all()
    fake.script(Scripted(purpose="interviewer", json={"entries": []}))
    return sid


async def test_interview_completion_triggers_draft_and_versions_api(app_client):
    user, headers, project = await setup_project(app_client)
    # an admin-provided library component the author can depend on
    comp = await app_client.post(
        "/api/v1/library",
        json={
            "kind": "mcp_server",
            "slug": "email-mcp",
            "name": "Email MCP",
            "description": "Send and read email via IMAP/SMTP",
            "tools": [{"name": "send_email", "description": "send", "side_effects": "irreversible"}],
            "env_requirements": [{"name": "SMTP_PASSWORD", "description": "smtp password", "secret": True}],
            "install": {"command": "email-mcp", "args": ["--stdio"], "hint": "pipx install email-mcp"},
        },
        headers=headers,
    )
    assert comp.status_code == 201
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        sid = await run_interview_to_completion(app_client, headers, project, fake)
        spec = sample_spec().model_dump()
        spec["dependencies"] = [
            {"component_slug": "email-mcp", "reason": "sending"},
            {"component_slug": "ghost", "reason": "unknown"},
        ]
        fake.script(Scripted(purpose="author", json=spec))
        confirmed = await app_client.post(
            f"/api/v1/interviews/{sid}/confirm", json={"confirmed": True}, headers=headers
        )
        assert confirmed.status_code == 200
        await get_job_runner().wait_all()
        detail = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()
        # `wait_all` has waited for the draft job too, so the interview must have been let out of
        # `drafting_requested` again: that state means "a first draft is being written", and a page
        # reading it as still-working is what used to leave a finished interview under a spinner.
        assert detail["session"]["state"] == "complete", detail["session"]
        skill_id = detail["session"]["skill_id"]
        versions_res = await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)
        assert versions_res.status_code == 200, versions_res.text
        versions = versions_res.json()
        assert len(versions) == 1
        v = versions[0]
        assert (
            v["version"] == "0.1.0" and v["state"] == "draft" and v["origin"] == "interview" and v["is_current_draft"]
        )
        assert v["validation_report"]["ok"] is True and v["signature"]
        assert {f["path"] for f in v["manifest"]["files"]} == {"SKILL.md", "references/columns.md"}

        vd = (await app_client.get(f"/api/v1/versions/{v['id']}", headers=headers)).json()
        assert [s["key"] for s in vd["steps"]] == ["open-sheet", "flag", "send"]
        send = vd["steps"][2]
        assert (
            send["trial_mode"] == "simulate"
            and send["requires_explicit_auth"] is True
            and send["library_component_slug"] == "email-mcp"
        )
        assert vd["dependencies"] == [{"component_slug": "email-mcp", "reason": "sending", "version_constraint": None}]
        assert "attempt 1: ok" in vd["build_log"]

        md = (await app_client.get(f"/api/v1/versions/{v['id']}/files/SKILL.md", headers=headers)).json()
        assert md["content"].startswith("---\nname: invoice-check") and "<!-- step:flag -->" in md["content"]
        missing = await app_client.get(f"/api/v1/versions/{v['id']}/files/nope.md", headers=headers)
        assert missing.status_code == 404

        install = (await app_client.get(f"/api/v1/versions/{v['id']}/install/hermes", headers=headers)).json()
        # The guide shown inside the application is the short one: the person is logged in, already has
        # the CLI, and the download links are controls on the same page. What it must still carry is
        # what the CLI will ask them for.
        assert "Email MCP" in install["markdown"] and "SMTP_PASSWORD" in install["markdown"]
        assert "## Manual installation" not in install["markdown"]
        assert f"--version-id {v['id']}" in install["markdown"] or "--from" in install["markdown"]
        # The public document keeps all of it, for an agent following the URL alone; that side is
        # covered by test_the_in_app_guide_is_short_and_the_public_one_is_complete in test_packaging.
        bad_target = await app_client.get(f"/api/v1/versions/{v['id']}/install/vim", headers=headers)
        assert bad_target.status_code == 422

        zip_res = await app_client.get(
            f"/api/v1/versions/{v['id']}/package.zip?targets=hermes,openclaw", headers=headers
        )
        assert zip_res.status_code == 200 and zip_res.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
            names = set(zf.namelist())
            assert {
                "invoice-check/SKILL.md",
                "invoice-check/INSTALL.hermes.md",
                "invoice-check/INSTALL.openclaw.md",
                "invoice-check/autoskill.json",
            } <= names
        skill = (await app_client.get(f"/api/v1/skills/{skill_id}", headers=headers)).json()
        assert skill["latest_version_id"] == v["id"]

        # regenerate as a patch -> 0.1.1 with parent; the first draft loses the current-draft flag
        patched = sample_spec().model_dump()
        patched["changelog"] = "patched"
        fake.script(Scripted(purpose="author", json=patched))
        gen = await app_client.post(
            f"/api/v1/skills/{skill_id}/versions/generate",
            json={"mode": "patch", "instructions": "be stricter"},
            headers=headers,
        )
        assert gen.status_code == 202
        await get_job_runner().wait_all()
        versions = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)).json()
        assert [x["version"] for x in versions] == ["0.1.1", "0.1.0"]
        assert (
            versions[0]["parent_version_id"] == v["id"]
            and versions[0]["is_current_draft"]
            and not versions[1]["is_current_draft"]
        )
        author_calls = [c for c in fake.calls if c.purpose == "author"]
        assert (
            "PATCH" in author_calls[-1].messages[-1].content and "be stricter" in author_calls[-1].messages[-1].content
        )

        discarded = await app_client.post(f"/api/v1/versions/{versions[0]['id']}/discard", headers=headers)
        assert discarded.json()["state"] == "discarded"
        skill = (await app_client.get(f"/api/v1/skills/{skill_id}", headers=headers)).json()
        assert skill["latest_version_id"] == v["id"]
    finally:
        set_fake_provider(None)


async def test_draft_repairs_validation_errors_once(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        sid = await run_interview_to_completion(app_client, headers, project, fake)
        broken = sample_spec().model_dump()
        broken["files"] = [{"path": "scripts/bad.py", "content": "def (:\n"}]
        fake.script(
            Scripted(purpose="author", json=broken), Scripted(purpose="author", json=sample_spec().model_dump())
        )
        await app_client.post(f"/api/v1/interviews/{sid}/confirm", json={"confirmed": True}, headers=headers)
        await get_job_runner().wait_all()
        skill_id = (await app_client.get(f"/api/v1/interviews/{sid}", headers=headers)).json()["session"]["skill_id"]
        versions = (await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)).json()
        assert len(versions) == 1
        vd = (await app_client.get(f"/api/v1/versions/{versions[0]['id']}", headers=headers)).json()
        assert "attempt 1: validation errors" in vd["build_log"] and "attempt 2: ok" in vd["build_log"]
        repair_call = [c for c in fake.calls if c.purpose == "author"][-1]
        assert "python_syntax" in repair_call.messages[-1].content

        # still broken after the repair -> job fails, no version created
        fake.script(Scripted(purpose="author", json=broken), Scripted(purpose="author", json=broken))
        await app_client.post(f"/api/v1/skills/{skill_id}/versions/generate", json={"mode": "new"}, headers=headers)
        await get_job_runner().wait_all()
        jobs = (await app_client.get("/api/v1/admin/jobs?status=failed", headers=headers)).json()["items"]
        assert any("draft failed validation" in (j["error"] or "") for j in jobs)
        assert len((await app_client.get(f"/api/v1/skills/{skill_id}/versions", headers=headers)).json()) == 1
    finally:
        set_fake_provider(None)


async def test_library_admin_only(app_client):
    admin = await register(app_client, "alice@example.com")
    bob = await register(app_client, "bob@example.com")
    a, b = auth(admin["access_token"]), auth(bob["access_token"])
    denied = await app_client.post(
        "/api/v1/library", json={"kind": "skill", "slug": "ldap-helper", "name": "LDAP", "description": "d"}, headers=b
    )
    assert denied.status_code == 403
    created = await app_client.post(
        "/api/v1/library",
        json={
            "kind": "skill",
            "slug": "ldap-helper",
            "name": "LDAP",
            "description": "Look up people in the directory",
            "is_enabled": False,
        },
        headers=a,
    )
    assert created.status_code == 201
    dup = await app_client.post(
        "/api/v1/library", json={"kind": "skill", "slug": "ldap-helper", "name": "x", "description": "d"}, headers=a
    )
    assert dup.status_code == 409
    assert (await app_client.get("/api/v1/library", headers=b)).json() == []
    assert len((await app_client.get("/api/v1/library?include_disabled=true", headers=a)).json()) == 1
    updated = await app_client.put(
        f"/api/v1/library/{created.json()['id']}",
        json={**created.json(), "is_enabled": True, "tags": ["directory"]},
        headers=a,
    )
    assert updated.status_code == 200 and updated.json()["tags"] == ["directory"]
    assert len((await app_client.get("/api/v1/library", headers=b)).json()) == 1
    assert (await app_client.delete(f"/api/v1/library/{created.json()['id']}", headers=a)).status_code == 200


# --- a trial copy must announce that it is one -------------------------------------------------


def test_a_trial_copy_says_so_before_the_procedure_starts():
    """The trial instructions must reach the agent before it starts acting, not after.

    Learnt from the first real trial. The companion protocol sat at the end of a long SKILL.md and
    began "otherwise skip it silently"; the trial marker existed only in the frontmatter, where it
    named the trial without saying what being in one required. So a trial copy read exactly like a
    permanent one: the agent worked through the task by hand, raised no checkpoint, got half of it
    wrong, reported success — and the person's page waited for a step that could never arrive.
    """
    from autoskill.services.drafting.assemble import with_trial_preamble

    body = "# Fill the latest list\n\n## Purpose\nUpdate the workbook.\n\n## Steps\n"
    out = with_trial_preamble(body, trial_id="t-1", name="excel-lists", version="0.1.0")

    head, _, rest = out.partition("## Purpose")
    assert head.startswith("# Fill the latest list"), "the title still opens the file"
    # everything the agent must know is above the first section of the procedure
    assert "trial `t-1`" in head
    assert "start_run" in head and 'skill_name="excel-lists"' in head and 'skill_version="0.1.0"' in head
    assert "stop and say so" in head, "a missing companion must halt the run, not be worked around"
    assert rest.strip().startswith("Update the workbook."), "the body itself is untouched"


def test_a_body_without_a_title_still_gets_the_preamble():
    from autoskill.services.drafting.assemble import with_trial_preamble

    out = with_trial_preamble("Just prose.\n", trial_id="t-2", name="s", version="1")
    assert out.startswith("> ##") and out.rstrip().endswith("Just prose.")


def test_outside_a_trial_the_protocol_stays_optional():
    """A permanent installation has no page waiting on it, so absent tools must not stop the work."""
    from autoskill.services.drafting.assemble import COMPANION_SECTION

    text = COMPANION_SECTION.format(name="s", version="1")
    assert "Outside a trial they are optional" in text
    assert "In a trial they are\nmandatory" in text or "mandatory" in text
    assert "skip it silently" not in text


def test_the_protocol_shipped_is_the_one_the_server_enforces():
    """The companion section describes the server's rules, so it is written at delivery, not at drafting.

    It used to be baked into SKILL.md when the skill was drafted and never touched again. Correcting
    the wording — after a trial where an agent read "`continue` proceeds" as "move to the next step"
    and abandoned the walkthrough — therefore changed nothing for any skill that already existed: the
    packages went on shipping the old text, and agents went on following it. A rule and its
    description must not be able to drift.
    """
    from autoskill.services.drafting.assemble import with_current_protocol

    stale = (
        "# Fill the list\n\n## Steps\n\ndo the thing\n\n"
        "## AutoSkill companion (checkpoints and telemetry)\n\n"
        "If the `autoskill-companion` MCP tools are available, follow this protocol; "
        "otherwise skip it silently.\n\n1. Call `start_run` the old way.\n"
    )
    out = with_current_protocol(stale, name="excel-lists", version="0.1.0")

    assert "skip it silently" not in out, "the superseded wording must not survive delivery"
    assert "two checkpoints" in out, "the current two-gate wording must be the one shipped"
    assert 'skill_name="excel-lists"' in out and 'skill_version="0.1.0"' in out
    # only the protocol is replaced; the skill's own content is not touched
    assert "# Fill the list" in out and "do the thing" in out
    assert out.count("## AutoSkill companion") == 1


def test_a_package_without_the_section_gains_it():
    from autoskill.services.drafting.assemble import with_current_protocol

    out = with_current_protocol("# Title\n\nJust steps.\n", name="s", version="1")
    assert "## AutoSkill companion" in out and out.startswith("# Title")
