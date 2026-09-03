from tests.conftest import auth, register


async def test_project_lifecycle_and_membership(app_client):
    alice = await register(app_client, "alice@example.com")
    bob = await register(app_client, "bob@example.com")
    carol = await register(app_client, "carol@example.com")
    a, b, c = auth(alice["access_token"]), auth(bob["access_token"]), auth(carol["access_token"])

    created = await app_client.post("/api/v1/projects", json={"name": "Invoices Ops"}, headers=b)
    assert created.status_code == 201
    project = created.json()
    assert project["slug"] == "invoices-ops" and project["my_role"] == "owner"

    # carol is not a member
    denied = await app_client.get(f"/api/v1/projects/{project['id']}", headers=c)
    assert denied.status_code == 403
    # admin sees everything
    seen = await app_client.get(f"/api/v1/projects/{project['id']}", headers=a)
    assert seen.status_code == 200

    added = await app_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "carol@example.com", "role": "viewer"},
        headers=b,
    )
    assert added.status_code == 201
    member_id = added.json()["id"]
    now_ok = await app_client.get(f"/api/v1/projects/{project['id']}", headers=c)
    assert now_ok.status_code == 200 and now_ok.json()["my_role"] == "viewer"
    # viewer cannot edit
    edit = await app_client.patch(f"/api/v1/projects/{project['id']}", json={"name": "X"}, headers=c)
    assert edit.status_code == 403

    # cannot demote the last owner
    owners = await app_client.get(f"/api/v1/projects/{project['id']}/members", headers=b)
    owner_member = next(m for m in owners.json() if m["role"] == "owner")
    demote = await app_client.patch(
        f"/api/v1/projects/{project['id']}/members/{owner_member['id']}",
        json={"role": "editor"},
        headers=b,
    )
    assert demote.status_code == 422

    removed = await app_client.delete(f"/api/v1/projects/{project['id']}/members/{member_id}", headers=b)
    assert removed.status_code == 200
    listing = await app_client.get("/api/v1/projects", headers=c)
    assert listing.json() == []

    # slug uniqueness
    again = await app_client.post("/api/v1/projects", json={"name": "Invoices Ops"}, headers=b)
    assert again.json()["slug"] == "invoices-ops-2"


async def test_project_api_keys(app_client):
    bob = await register(app_client, "bob@example.com")
    b = auth(bob["access_token"])
    project = (await app_client.post("/api/v1/projects", json={"name": "P"}, headers=b)).json()
    bad = await app_client.post(
        f"/api/v1/projects/{project['id']}/api-keys",
        json={"name": "k", "scopes": ["nope"]},
        headers=b,
    )
    assert bad.status_code == 422
    created = await app_client.post(
        f"/api/v1/projects/{project['id']}/api-keys",
        json={"name": "telemetry", "scopes": ["telemetry:write"]},
        headers=b,
    )
    assert created.status_code == 201
    key = created.json()
    assert key["key"].startswith(key["key_prefix"])
    listed = await app_client.get(f"/api/v1/projects/{project['id']}/api-keys", headers=b)
    assert len(listed.json()) == 1 and "key" not in listed.json()[0]
    revoked = await app_client.delete(f"/api/v1/api-keys/{key['id']}", headers=b)
    assert revoked.status_code == 200
    # revoked key cannot heartbeat
    hb = await app_client.post("/api/v1/devices/heartbeat", json={}, headers=auth(key["key"]))
    assert hb.status_code == 401
