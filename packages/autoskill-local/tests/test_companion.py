import json

import httpx

from autoskill_local import companion
from autoskill_local.client import Client
from autoskill_local.config import HOME


def make_transport(state: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        state.setdefault("calls", []).append((request.method, request.url.path, request.headers.get("x-autoskill-trial"), json.loads(request.content or b"null")))
        path = request.url.path
        if path.endswith("/telemetry/runs"):
            return httpx.Response(200, json={"run_id": "run1", "trial_session_id": "t1", "mode": "interactive", "skill_version": "0.1.0"})
        if path.endswith("/checkpoints"):
            return httpx.Response(200, json={"status": "pending", "checkpoint_id": "cp1"})
        if path.endswith("/checkpoints/cp1"):
            state["polls"] = state.get("polls", 0) + 1
            if state["polls"] < 2:
                return httpx.Response(200, json={"status": "pending", "checkpoint_id": "cp1"})
            return httpx.Response(200, json={"status": "decided", "checkpoint_id": "cp1", "decision": "change", "updated_instructions": "do it better"})
        if path.endswith("/steps"):
            if state.get("fail_steps"):
                return httpx.Response(503, json={"error": {"code": "down", "message": "maintenance"}})
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/end"):
            return httpx.Response(409, json={"error": {"code": "run_not_running", "message": "already ended"}})
        if "/telemetry/guidance/" in path:
            return httpx.Response(200, json={"step_key": "flag", "corrections": [], "memory": []})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})

    return httpx.MockTransport(handler)


async def test_tools_are_registered():
    names = {t.name for t in await companion.mcp.list_tools()}
    assert names == {"start_run", "checkpoint", "await_decision", "log_step", "end_run", "report_issue", "get_step_guidance"}


def test_tool_functions_talk_to_the_server_and_degrade_gracefully(tmp_path, monkeypatch):
    state: dict = {}
    client = Client("http://server", api_key="ask_key", trial_token="tok", transport=make_transport(state))
    client.queue_path = tmp_path / "queue.jsonl"
    companion.set_client(client)
    try:
        run = companion.start_run("invoice-check", "0.1.0", "hermes")
        assert run["run_id"] == "run1"
        cp = companion.checkpoint("run1", "flag", "explain", {"explanation": "x"})
        assert cp["status"] == "pending"
        first = companion.await_decision("cp1", 5)
        assert first["status"] == "pending"  # the agent repeats the call while pending
        decided = companion.await_decision("cp1", 5)
        assert decided["decision"] == "change" and decided["updated_instructions"] == "do it better"
        assert state["polls"] == 2
        # trial token and api key travel with every call
        _method, _path, trial_header, body = state["calls"][0]
        assert trial_header == "tok" and body["skill_name"] == "invoice-check"
        assert companion.log_step("run1", "flag", "succeeded", outputs={"rows": 3})["ok"] is True
        # 4xx errors are returned, not raised
        ended = companion.end_run("run1", "succeeded")
        assert ended["error"] == "run_not_running"
        # 5xx on telemetry -> queued locally, then flushed on the next successful call
        state["fail_steps"] = True
        queued = companion.log_step("run1", "flag", "failed", error="boom")
        assert queued == {"queued": True} and client.queue_path.exists()
        state["fail_steps"] = False
        companion.log_step("run1", "flag", "succeeded")
        assert not client.queue_path.exists()
        assert companion.get_step_guidance("s1", "flag")["step_key"] == "flag"
    finally:
        companion.set_client(None)


def test_unreachable_server_returns_error_dict(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("no route")

    client = Client("http://server", transport=httpx.MockTransport(boom))
    companion.set_client(client)
    try:
        res = companion.start_run("x")
        assert res["error"] == "unreachable"
    finally:
        companion.set_client(None)
    assert HOME.name
