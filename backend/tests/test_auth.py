from tests.conftest import auth, register


async def test_first_user_is_admin_then_members(app_client):
    first = await register(app_client, "alice@example.com")
    assert first["user"]["role"] == "admin"
    second = await register(app_client, "bob@example.com")
    assert second["user"]["role"] == "member"
    dup = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "password123", "display_name": "Bob"},
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "email_taken"


async def test_login_refresh_logout(app_client):
    await register(app_client, "alice@example.com")
    bad = await app_client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    ok = await app_client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "password123"})
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    me = await app_client.get("/api/v1/auth/me", headers=auth(token))
    assert me.status_code == 200 and me.json()["email"] == "alice@example.com"
    assert "autoskill_refresh" in app_client.cookies
    refreshed = await app_client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
    out = await app_client.post("/api/v1/auth/logout")
    assert out.status_code == 200
    again = await app_client.post("/api/v1/auth/refresh")
    assert again.status_code == 401


async def test_registration_can_be_closed(app_client):
    admin = await register(app_client, "alice@example.com")
    res = await app_client.put(
        "/api/v1/admin/settings",
        json={"values": {"registration_open": False}},
        headers=auth(admin["access_token"]),
    )
    assert res.status_code == 200 and res.json()["registration_open"] is False
    closed = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "eve@example.com", "password": "password123", "display_name": "Eve"},
    )
    assert closed.status_code == 403


async def test_device_code_flow(app_client):
    user = await register(app_client, "alice@example.com")
    start = await app_client.post(
        "/api/v1/auth/device",
        json={"device_name": "laptop", "device_os": "linux", "agent_targets": ["hermes"]},
    )
    assert start.status_code == 200
    data = start.json()
    pending = await app_client.post("/api/v1/auth/device/token", json={"device_code": data["device_code"]})
    assert pending.json()["status"] == "pending"
    info = await app_client.get(f"/api/v1/auth/device/pending/{data['user_code']}", headers=auth(user["access_token"]))
    assert info.status_code == 200 and info.json()["device_name"] == "laptop"
    confirm = await app_client.post(
        "/api/v1/auth/device/confirm",
        json={"user_code": data["user_code"].lower()},
        headers=auth(user["access_token"]),
    )
    assert confirm.status_code == 200
    approved = await app_client.post("/api/v1/auth/device/token", json={"device_code": data["device_code"]})
    body = approved.json()
    assert body["status"] == "approved" and body["api_key"].startswith("ask_")
    # key is delivered once
    consumed = await app_client.post("/api/v1/auth/device/token", json={"device_code": data["device_code"]})
    assert consumed.json()["status"] == "consumed"
    # the key authenticates CLI endpoints and heartbeat
    devices = await app_client.get("/api/v1/me/devices", headers=auth(body["api_key"]))
    assert devices.status_code == 200 and devices.json()[0]["name"] == "laptop"
    hb = await app_client.post(
        "/api/v1/devices/heartbeat",
        json={"cli_version": "0.1.0", "agent_targets": ["hermes", "openclaw"]},
        headers=auth(body["api_key"]),
    )
    assert hb.status_code == 200 and hb.json()["agent_targets"] == ["hermes", "openclaw"]
    # a JWT-only endpoint rejects the API key
    me = await app_client.get("/api/v1/auth/me", headers=auth(body["api_key"]))
    assert me.status_code == 401
