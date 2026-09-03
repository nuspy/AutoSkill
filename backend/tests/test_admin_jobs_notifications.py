import asyncio

from autoskill.api.v1.events import _stream
from autoskill.core.events import user_channel
from autoskill.core.jobs import get_job_runner
from autoskill.db.session import get_session_factory
from autoskill.services.notifications import notify
from tests.conftest import auth, register


async def test_admin_endpoints_and_role_guards(app_client):
    alice = await register(app_client, "alice@example.com")
    bob = await register(app_client, "bob@example.com")
    a, b = auth(alice["access_token"]), auth(bob["access_token"])

    forbidden = await app_client.get("/api/v1/admin/users", headers=b)
    assert forbidden.status_code == 403
    users = await app_client.get("/api/v1/admin/users", headers=a)
    assert users.status_code == 200 and users.json()["total"] == 2

    promoted = await app_client.patch(f"/api/v1/admin/users/{bob['user']['id']}", json={"role": "reviewer"}, headers=a)
    assert promoted.status_code == 200 and promoted.json()["role"] == "reviewer"
    self_demote = await app_client.patch(
        f"/api/v1/admin/users/{alice['user']['id']}", json={"role": "member"}, headers=a
    )
    assert self_demote.status_code == 422

    stats = await app_client.get("/api/v1/admin/stats", headers=a)
    assert stats.json()["users"] == 2
    audit = await app_client.get("/api/v1/admin/audit", headers=a)
    actions = {row["action"] for row in audit.json()["items"]}
    assert {"user.register", "admin.user_update"} <= actions

    unknown = await app_client.put("/api/v1/admin/settings", json={"values": {"nope": 1}}, headers=a)
    assert unknown.status_code == 422


async def test_inline_job_runner_records_result(app_client):
    alice = await register(app_client, "alice@example.com")
    runner = get_job_runner()
    row = await runner.enqueue("system.ping", {"x": 1}, user_id=alice["user"]["id"])
    await runner.wait_all()
    jobs = await app_client.get("/api/v1/admin/jobs", headers=auth(alice["access_token"]))
    item = next(j for j in jobs.json()["items"] if j["id"] == row.id)
    assert item["status"] == "succeeded" and item["progress"] == 100

    failing = await runner.enqueue("does.not.exist", {})
    await runner.wait_all()
    jobs = await app_client.get("/api/v1/admin/jobs?status=failed", headers=auth(alice["access_token"]))
    assert any(j["id"] == failing.id and "unknown job" in (j["error"] or "") for j in jobs.json()["items"])


async def test_notifications_and_sse(app_client):
    alice = await register(app_client, "alice@example.com")
    a = auth(alice["access_token"])
    uid = alice["user"]["id"]

    class FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    stream = _stream(FakeRequest(), user_channel(uid))
    first = await stream.__anext__()
    assert first["event"] == "ready"

    async with get_session_factory()() as session:
        await notify(session, uid, "review_requested", "Please review X", subject_type="skill_version")
        await session.commit()
    event = await asyncio.wait_for(stream.__anext__(), timeout=5)
    assert event["event"] == "notification.created"
    assert '"unread": 1' in event["data"]
    await stream.aclose()

    listing = await app_client.get("/api/v1/me/notifications", headers=a)
    assert listing.json()["unread"] == 1
    nid = listing.json()["items"][0]["id"]
    await app_client.post(f"/api/v1/me/notifications/{nid}/read", headers=a)
    listing = await app_client.get("/api/v1/me/notifications?unread_only=true", headers=a)
    assert listing.json()["unread"] == 0 and listing.json()["items"] == []
