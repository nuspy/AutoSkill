"""The install command must be recoverable, because nothing starts a trial without it.

`POST /trials` returns the command once — it carries a bearer token, and only the hash is stored. A
person who closed that dialog was left on a trial page that said "run the CLI command" about a
command nothing in the system could produce any more, while the trial sat in `requested` waiting for
a machine nobody had told. Even the fallback ("hand this address to your agent") dead-ends in the
same place: it ends by asking the person for the trial token.

The trial now keeps a readable copy of its own token, so the page shows the command that was already
issued and displaying it changes nothing. Re-issuing remains for the trials created before that copy
existed, and it replaces rather than reveals: the previous token stops working.
"""

from __future__ import annotations

from httpx import AsyncClient

from autoskill.llm.fake import FakeLlmProvider
from autoskill.llm.registry import set_fake_provider
from tests.conftest import auth, register
from tests.test_bundle import _draft_with_dependencies


async def _open_trial(app_client: AsyncClient) -> tuple[dict, dict]:
    user = await register(app_client, "alice@example.com")
    headers = auth(user["access_token"])
    project = (await app_client.post("/api/v1/projects", json={"name": "Ops"}, headers=headers)).json()
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        _, version = await _draft_with_dependencies(app_client, headers, project, fake, [])
        created = await app_client.post(
            "/api/v1/trials",
            json={"skill_version_id": version["id"], "target_agent": "openclaw", "purpose": "develop"},
            headers=headers,
        )
    finally:
        set_fake_provider(None)
    assert created.status_code == 201, created.text
    return created.json(), headers


async def test_the_install_command_can_be_asked_for_again(app_client: AsyncClient) -> None:
    trial, headers = await _open_trial(app_client)

    again = await app_client.post(f"/api/v1/trials/{trial['id']}/command", headers=headers)
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["cli_command"] == (
        f"autoskill trial install --from {body['manifest_url']} --target openclaw --token {body['session_token']}"
    )
    assert body["session_token"] != trial["session_token"], "a re-issue must mint a new token, not repeat the old one"

    # the new token works where the trial token is the only credential
    accepted = await app_client.post(
        f"/api/v1/trials/{trial['id']}/installed",
        json={"install_manifest": {"target": "openclaw", "manual": True}, "build": 1},
        headers={"X-AutoSkill-Trial": body["session_token"]},
    )
    assert accepted.status_code == 200, accepted.text


async def test_the_previous_token_stops_working(app_client: AsyncClient) -> None:
    """Said out loud in the interface, and true: re-issuing revokes what came before."""
    trial, headers = await _open_trial(app_client)
    await app_client.post(f"/api/v1/trials/{trial['id']}/command", headers=headers)

    stale = await app_client.post(
        f"/api/v1/trials/{trial['id']}/installed",
        json={"install_manifest": {"target": "openclaw", "manual": True}, "build": 1},
        headers={"X-AutoSkill-Trial": trial["session_token"]},
    )
    assert stale.status_code >= 400, "the token shown before the re-issue must no longer open the trial"


async def test_somebody_elses_trial_stays_shut(app_client: AsyncClient) -> None:
    trial, _ = await _open_trial(app_client)
    other = await register(app_client, "mallory@example.com")

    refused = await app_client.post(
        f"/api/v1/trials/{trial['id']}/command", headers=auth(other["access_token"])
    )
    assert refused.status_code in (403, 404), refused.text


async def test_the_page_gets_the_trial_own_command_without_minting_a_new_one(app_client: AsyncClient) -> None:
    """Looking at the install command must not invalidate the token an agent may already hold.

    Re-issuing was the only way back to it, because only the hash was stored. That made recovering
    the instruction destructive: whoever had already pasted the command into an agent broke that
    installation by asking to see it again. A readable copy — the pair DownloadGrant already used,
    hash for lookup and encrypted for display — makes reading a read.
    """
    trial, headers = await _open_trial(app_client)
    issued = trial["session_token"]

    detail = (await app_client.get(f"/api/v1/trials/{trial['id']}", headers=headers)).json()
    assert detail["session_token"] == issued, "the same token, not a new one"
    assert detail["cli_command"] == trial["cli_command"]

    # reading it twice changes nothing, and the token still authenticates
    again = (await app_client.get(f"/api/v1/trials/{trial['id']}", headers=headers)).json()
    assert again["session_token"] == issued
    run = await app_client.post(
        "/api/v1/telemetry/runs",
        json={"skill_name": detail["skill_name"], "agent_target": "openclaw"},
        headers={"X-AutoSkill-Trial": issued},
    )
    assert run.status_code == 200, run.text

    # re-issuing still replaces it, and the page then reports the new one
    fresh = (await app_client.post(f"/api/v1/trials/{trial['id']}/command", headers=headers)).json()
    assert fresh["session_token"] != issued
    after = (await app_client.get(f"/api/v1/trials/{trial['id']}", headers=headers)).json()
    assert after["session_token"] == fresh["session_token"]
