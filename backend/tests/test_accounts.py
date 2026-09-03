"""Invitations, password reset and notification emails (console backend outbox)."""

from autoskill.db.session import get_session_factory
from autoskill.services.email import OUTBOX
from autoskill.services.notifications import notify
from tests.conftest import auth, register
from tests.test_interview import setup_project


async def test_invitations_and_closed_registration(app_client):
    _admin, a, project = await setup_project(app_client)
    await app_client.put("/api/v1/admin/settings", json={"values": {"registration_open": False}}, headers=a)
    closed = await app_client.post(
        "/api/v1/auth/register", json={"email": "bob@example.com", "password": "password123", "display_name": "Bob"}
    )
    assert closed.status_code == 403 and closed.json()["error"]["code"] == "registration_closed"

    inv = await app_client.post(
        "/api/v1/admin/invitations",
        json={"email": "Bob@Example.com", "role": "reviewer", "project_id": project["id"]},
        headers=a,
    )
    assert inv.status_code == 201, inv.text
    inv = inv.json()
    assert inv["email"] == "bob@example.com" and inv["invite_url"].startswith("http://localhost:8000/invite/")
    token = inv["invite_url"].rsplit("/", 1)[1]
    mail = next(m for m in OUTBOX if m.kind == "invite")
    assert mail.to == "bob@example.com" and inv["invite_url"] in mail.text and "invited" in mail.subject
    listed = (await app_client.get("/api/v1/admin/invitations", headers=a)).json()
    assert [x["id"] for x in listed] == [inv["id"]] and listed[0].get("invite_url") is None
    # duplicate for an existing account is refused
    dup = await app_client.post("/api/v1/admin/invitations", json={"email": "alice@example.com"}, headers=a)
    assert dup.status_code == 409

    # the invite page can read the invitation; registration must use the invited address
    info = await app_client.get(f"/api/v1/auth/invite/{token}")
    assert info.status_code == 200 and info.json() == {"email": "bob@example.com", "role": "reviewer", "project": "Ops"}
    assert (await app_client.get("/api/v1/auth/invite/nope")).status_code == 404
    wrong = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "password123", "display_name": "X", "invite_token": token},
    )
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "invite_email_mismatch"
    ok = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "password123", "display_name": "Bob", "invite_token": token},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["user"]["role"] == "reviewer"
    b = auth(ok.json()["access_token"])
    members = (await app_client.get(f"/api/v1/projects/{project['id']}/members", headers=a)).json()
    assert any(m["user_id"] == ok.json()["user"]["id"] and m["role"] == "editor" for m in members)
    assert (await app_client.get(f"/api/v1/projects/{project['id']}", headers=b)).status_code == 200
    # the token is single use
    again = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "password123", "display_name": "Bob", "invite_token": token},
    )
    assert again.status_code == 409
    assert (await app_client.get("/api/v1/admin/invitations", headers=a)).json() == []
    assert (await app_client.delete(f"/api/v1/admin/invitations/{inv['id']}", headers=a)).status_code == 200


async def test_password_reset_flow(app_client):
    user = await register(app_client, "carol@example.com", password="oldpassword1", name="Carol")
    # unknown addresses get the same answer and no mail
    assert (
        await app_client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.com"})
    ).status_code == 200
    assert not [m for m in OUTBOX if m.kind == "password_reset"]
    assert (
        await app_client.post("/api/v1/auth/password/forgot", json={"email": "Carol@example.com"})
    ).status_code == 200
    mail = next(m for m in OUTBOX if m.kind == "password_reset")
    assert mail.to == "carol@example.com" and "Carol" in mail.text
    token = next(line for line in mail.text.splitlines() if "/reset/" in line).rsplit("/", 1)[1]
    bad = await app_client.post(
        "/api/v1/auth/password/reset", json={"token": "wrong-token", "new_password": "newpassword1"}
    )
    assert bad.status_code == 404
    ok = await app_client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": "newpassword1"})
    assert ok.status_code == 200, ok.text
    old = await app_client.post("/api/v1/auth/login", json={"email": "carol@example.com", "password": "oldpassword1"})
    assert old.status_code == 401
    new = await app_client.post("/api/v1/auth/login", json={"email": "carol@example.com", "password": "newpassword1"})
    assert new.status_code == 200
    used = await app_client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": "another1234"})
    assert used.status_code == 409
    assert user["user"]["email"] == "carol@example.com"


async def test_notification_email_preferences(app_client):
    admin, a, _project = await setup_project(app_client)
    prefs = (await app_client.get("/api/v1/me/notifications/preferences", headers=a)).json()
    by_kind = {p["kind"]: p for p in prefs}
    assert by_kind["review_requested"]["email"] is True and by_kind["checkpoint_waiting"]["email"] is False
    bad = await app_client.put("/api/v1/me/notifications/preferences", json={"kind": "nope", "email": True}, headers=a)
    assert bad.status_code == 422
    await app_client.put(
        "/api/v1/me/notifications/preferences",
        json={"kind": "checkpoint_waiting", "in_app": True, "email": True},
        headers=a,
    )
    await app_client.put(
        "/api/v1/me/notifications/preferences",
        json={"kind": "review_requested", "in_app": True, "email": False},
        headers=a,
    )
    uid = admin["user"]["id"]
    async with get_session_factory()() as session:
        await notify(
            session,
            uid,
            "checkpoint_waiting",
            "The agent is waiting",
            body="Step flag",
            subject_type="trial_session",
            subject_id="t1",
        )
        await notify(session, uid, "review_requested", "Review please", subject_type="review_request", subject_id="r1")
        await notify(
            session, uid, "proposal_ready", "Improvement proposed", subject_type="improvement_proposal", subject_id="p1"
        )
        await session.commit()
    mails = [m for m in OUTBOX if m.kind == "notification"]
    assert [m.subject for m in mails] == ["[AutoSkill] The agent is waiting", "[AutoSkill] Improvement proposed"]
    assert "http://localhost:8000/me/trials" in mails[0].text and "Step flag" in mails[0].text
    listed = (await app_client.get("/api/v1/me/notifications", headers=a)).json()
    assert listed["unread"] == 3
