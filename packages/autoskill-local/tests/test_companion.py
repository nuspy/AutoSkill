import json
from pathlib import Path

import httpx

from autoskill_local import companion
from autoskill_local.client import Client
from autoskill_local.config import HOME


def make_transport(state: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        state.setdefault("calls", []).append(
            (
                request.method,
                request.url.path,
                request.headers.get("x-autoskill-trial"),
                json.loads(request.content or b"null"),
            )
        )
        path = request.url.path
        if path.endswith("/telemetry/runs"):
            return httpx.Response(
                200, json={"run_id": "run1", "trial_session_id": "t1", "mode": "interactive", "skill_version": "0.1.0"}
            )
        if path.endswith("/checkpoints"):
            return httpx.Response(200, json={"status": "pending", "checkpoint_id": "cp1"})
        if path.endswith("/checkpoints/cp1"):
            state["polls"] = state.get("polls", 0) + 1
            if state["polls"] < 2:
                return httpx.Response(200, json={"status": "pending", "checkpoint_id": "cp1"})
            return httpx.Response(
                200,
                json={
                    "status": "decided",
                    "checkpoint_id": "cp1",
                    "decision": "change",
                    "updated_instructions": "do it better",
                },
            )
        if path.endswith("/steps"):
            if state.get("fail_steps"):
                return httpx.Response(503, json={"error": {"code": "down", "message": "maintenance"}})
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/end"):
            return httpx.Response(409, json={"error": {"code": "run_not_running", "message": "already ended"}})
        if path.endswith("/telemetry/snapshots"):
            body = json.loads(request.content)
            return httpx.Response(200, json={"id": "snap1", "items": body["items"], "iteration": 1})
        if "/telemetry/guidance/" in path:
            return httpx.Response(200, json={"step_key": "flag", "corrections": [], "memory": []})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})

    return httpx.MockTransport(handler)


async def test_tools_are_registered():
    names = {t.name for t in await companion.mcp.list_tools()}
    assert names == {
        "start_run",
        "checkpoint",
        "await_decision",
        "log_step",
        "end_run",
        "report_issue",
        "get_step_guidance",
        "snapshot",
        "restore_snapshot",
        # the executor side of an interview
        "assist_interview",
        "await_task",
        "report_task",
        "attach_file",
    }


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


def test_snapshot_and_restore_round_trip(tmp_path, monkeypatch):
    state: dict = {}
    client = Client("http://server", api_key="ask_key", trial_token="tok", transport=make_transport(state))
    companion.set_client(client)
    monkeypatch.setattr(companion, "HOME", tmp_path / ".autoskill")
    try:
        work = tmp_path / "work"
        work.mkdir()
        sheet = work / "invoices.xlsx"
        sheet.write_bytes(b"original")
        folder = work / "out"
        folder.mkdir()
        (folder / "a.txt").write_text("a")
        snap = companion.snapshot(
            "run1",
            "flag",
            paths=[str(sheet), str(folder), str(work / "missing.txt")],
            refs=[{"kind": "db", "ref": "table x"}],
        )
        # compared as a path, not as a string: the separator differs by platform and the test is
        # about where the snapshot went, not about how the operating system spells it
        assert snap["id"] == "snap1" and Path(snap["local_dir"]).parts[-3:] == ("sandbox", "run1", "flag")
        kinds = [i["kind"] for i in snap["items"]]
        assert kinds == ["file", "folder", "missing", "db"]
        sent = next(c for c in state["calls"] if c[1].endswith("/telemetry/snapshots"))
        assert sent[2] == "tok" and sent[3]["step_key"] == "flag" and len(sent[3]["items"]) == 4
        # the step damages the data; restore puts the copies back and reports a restore checkpoint
        sheet.write_bytes(b"changed")
        (folder / "a.txt").write_text("changed")
        (folder / "b.txt").write_text("new")
        res = companion.restore_snapshot("run1", "flag")
        assert res["checkpoint_id"] == "cp1" and sorted(res["restored"]) == sorted(
            [str(sheet.resolve()), str(folder.resolve())]
        )
        assert res["needs_manual_restore"] == [{"kind": "db", "ref": "table x", "note": None}]
        assert (
            sheet.read_bytes() == b"original"
            and (folder / "a.txt").read_text() == "a"
            and not (folder / "b.txt").exists()
        )
        cp_call = [c for c in state["calls"] if c[1].endswith("/checkpoints")][-1]
        assert cp_call[3]["phase"] == "restore" and cp_call[3]["proposal"]["restored"]
        assert companion.restore_snapshot("run1", "nope")["error"] == "no_snapshot"
    finally:
        companion.set_client(None)


# --- interview: this machine as the executor -------------------------------------------------


def interview_transport(state: dict, turns: list[dict]):
    """Serves the scripted turns in order, then records what gets reported back."""

    def handler(request: httpx.Request) -> httpx.Response:
        state.setdefault("calls", []).append((request.method, request.url.path, request.url.params.get("wait")))
        state["interview_header"] = request.headers.get("x-autoskill-interview")
        if request.method == "GET":
            turn = turns[min(state.get("polls", 0), len(turns) - 1)]
            state["polls"] = state.get("polls", 0) + 1
            return httpx.Response(200, json=turn)
        if request.url.path.endswith("/turn/attachments"):
            return httpx.Response(201, json={"name": "book.xlsx", "preview": "sheet 'S' ...", "hash": "h", "size": 9})
        state["reported"] = json.loads(request.content or b"null")
        return httpx.Response(200, json={"status": "accepted", "turn_id": 3})

    return httpx.MockTransport(handler)


def test_the_agent_joins_an_interview_and_waits_for_work(monkeypatch):
    state: dict = {}
    task = {"status": "task", "turn_id": 3, "for": "agent", "mode": "inspect",
            "instruction": "Look at ~/Invoices", "targets": ["~/Invoices"], "may_upload": True}
    turns = [{"status": "working", "state": "gating"}, {"status": "working", "state": "gating"}, task]
    companion.set_client(Client("http://server", api_key="ask_key", transport=interview_transport(state, turns)))
    monkeypatch.setattr(companion.time, "sleep", lambda _s: None, raising=False)
    try:
        first = companion.assist_interview(session_key="ask_iv_1")
        assert first["status"] == "working"
        assert state["interview_header"] == "ask_iv_1"

        # keeps polling while the application is thinking, then hands over the task
        got = companion.await_task(timeout_s=1, max_wait_s=10)
        assert got["status"] == "task" and got["targets"] == ["~/Invoices"]

        companion.report_task(text="sheet Invoices, columns A B", turn_id=got["turn_id"])
        assert state["reported"]["turn_id"] == 3
        assert "columns A B" in state["reported"]["text"]
    finally:
        companion.set_client(None)


def test_await_task_gives_up_instead_of_polling_for_ever(monkeypatch):
    state: dict = {}
    companion.set_client(
        Client("http://server", api_key="ask_key", transport=interview_transport(state, [{"status": "working"}]))
    )
    monkeypatch.setattr(companion.time, "sleep", lambda _s: None, raising=False)
    try:
        out = companion.await_task(session_key="ask_iv_1", timeout_s=1, max_wait_s=3)
        assert out["status"] == "timeout" and out["waited_s"] >= 3
    finally:
        companion.set_client(None)


def test_an_oversized_file_is_refused_without_asking_the_server(tmp_path):
    state: dict = {}
    companion.set_client(Client("http://server", api_key="ask_key", transport=interview_transport(state, [{}])))
    big = tmp_path / "huge.bin"
    big.write_bytes(b"x" * (companion.MAX_UPLOAD_BYTES + 1))
    try:
        out = companion.attach_file(path=str(big), session_key="ask_iv_1")
        assert out["error"] == "file_too_large"
        assert state.get("calls") is None  # nothing left the machine
    finally:
        companion.set_client(None)


def test_a_missing_file_says_so(tmp_path):
    companion.set_client(Client("http://server", api_key="ask_key", transport=interview_transport({}, [{}])))
    try:
        out = companion.attach_file(path=str(tmp_path / "nope.xlsx"), session_key="ask_iv_1")
        assert out["error"] == "not_a_file"
    finally:
        companion.set_client(None)
