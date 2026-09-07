"""autoskill-companion: MCP server (stdio) that installed skills call for checkpoints and telemetry.

Environment: AUTOSKILL_URL, AUTOSKILL_API_KEY (from `autoskill login` or a project key),
optional AUTOSKILL_SESSION_TOKEN (trial). Tools never raise on server errors: they return a dict
with "error" so the agent can continue and report the problem.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

try:  # mcp SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

from autoskill_local import __version__
from autoskill_local.client import Client, ServerError
from autoskill_local.config import HOME, LocalConfig

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # mirrors the server; refuse locally instead of uploading in vain

mcp = _Server(
    "autoskill-companion",
    # Read at every connection, unlike a skill document loaded once. Three consecutive trials were
    # carried out with a single checkpoint because the per-step cycle lived only in that document; the
    # cycle is therefore stated here too, in the shortest form that still says what to do.
    instructions=(
        "Checkpoints and run telemetry for AutoSkill skills, and the executor side of an AutoSkill "
        "interview.\n\n"
        "RUNNING A SKILL THAT IS ON TRIAL (its SKILL.md says so at the top): the person is watching "
        "each step in their browser and approving it. Call `start_run` once, then walk EVERY step of "
        "the skill through its own cycle — `checkpoint` explain, then preview, then execute (or "
        "straight to verify when the step is simulated), then verify — before you name the next step. "
        "A decision of `continue` means carry on inside the step you are in; only "
        "`approve_and_authorize_next` on a `verify` opens the following step. Every checkpoint reply "
        "carries `next_phase`, `next_step_key` and `next_hint`: do what it says, including when the "
        "reply is an error. Call `end_run` only after the last step has been verified — never as a way "
        "out of a refusal, because work done after that reaches the person as nothing at all.\n\n"
        "ASSISTING AN INTERVIEW: call `assist_interview` with the session key they paste, then loop "
        "`await_task` / `report_task` until it reports done. AutoSkill leads the interview and the "
        "person answers in their browser: you are not interviewing anyone. Carry out what is asked and "
        "report what you find. An `inspect` task is read-only — never change anything to answer one; a "
        "task in `act` mode goes through `checkpoint` first, like a trial step."
    ),
)

_client: Client | None = None
_state: dict[str, Any] = {"trial_token": None, "skill_id": None, "run_id": None, "interview": None}


def set_client(client: Client | None) -> None:
    """Tests inject a client with a mocked transport."""
    global _client
    _client = client


def get_client() -> Client:
    global _client
    if _client is None:
        cfg = LocalConfig.load()
        url = os.environ.get("AUTOSKILL_URL") or cfg.server_url
        if not url:
            raise RuntimeError("AUTOSKILL_URL is not set and no `autoskill login` was done")
        _state["trial_token"] = os.environ.get("AUTOSKILL_SESSION_TOKEN")
        _client = Client(
            url, api_key=os.environ.get("AUTOSKILL_API_KEY") or cfg.api_key, trial_token=_state["trial_token"]
        )
    return _client


def _call(fn):
    try:
        return fn()
    except ServerError as exc:
        return {"error": exc.code or "server_error", "message": str(exc), "status": exc.status}
    except Exception as exc:  # noqa: BLE001
        return {"error": "unreachable", "message": str(exc)}


@mcp.tool()
def start_run(
    skill_name: str,
    skill_version: str | None = None,
    agent_target: str | None = None,
    inputs_summary: str | None = None,
) -> dict:
    """Open a run before the first step. Returns run_id and the trial mode (interactive/async/production)."""

    def go():
        body = {
            "skill_name": skill_name,
            "skill_version": skill_version,
            "agent_target": agent_target,
            "inputs_summary": inputs_summary,
        }
        res = get_client().post("/telemetry/runs", body)
        _state["run_id"] = res["run_id"]
        return res

    return _call(go)


@mcp.tool()
def checkpoint(
    run_id: str, step_key: str, phase: str, proposal: dict | None = None, iteration: int | None = None
) -> dict:
    """Register a step phase (explain | preview | execute | verify) and get the decision, or 'pending'.

    In an interactive trial the person decides from the AutoSkill web UI: when the result is pending,
    call await_decision with the checkpoint_id until a decision arrives, then obey it.
    """

    def go():
        body = {
            "run_id": run_id,
            "step_key": step_key,
            "phase": phase,
            "proposal": proposal or {},
            "iteration": iteration,
        }
        return get_client().post("/checkpoints", body)

    return _call(go)


@mcp.tool()
def await_decision(checkpoint_id: str, timeout_s: int = 50) -> dict:
    """Wait (max 50 s per call) for the person's decision on a checkpoint. Repeat while status is 'pending'."""

    def go():
        return get_client().get(
            f"/checkpoints/{checkpoint_id}", params={"wait": max(0, min(int(timeout_s), 50))}, timeout=70
        )

    return _call(go)


@mcp.tool()
def log_step(
    run_id: str,
    step_key: str,
    status: str = "succeeded",
    title: str | None = None,
    inputs: dict | None = None,
    outputs: dict | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    tool_name: str | None = None,
) -> dict:
    """Record the outcome of a step (status: succeeded | failed | skipped | corrected)."""

    def go():
        body = {
            "step_key": step_key,
            "status": status,
            "title": title,
            "inputs": inputs,
            "outputs": outputs,
            "error": {"message": error} if error else None,
            "duration_ms": duration_ms,
            "tool_name": tool_name,
        }
        key = f"{run_id}:{step_key}:{int(time.time() * 1000)}"
        return get_client().post_or_queue(f"/telemetry/runs/{run_id}/steps", body, headers={"Idempotency-Key": key})

    return _call(go)


@mcp.tool()
def end_run(run_id: str, status: str = "succeeded", summary: str | None = None, error: str | None = None) -> dict:
    """Close the run (status: succeeded | failed | aborted | needs_review)."""

    def go():
        return get_client().post_or_queue(
            f"/telemetry/runs/{run_id}/end",
            {"status": status, "summary": summary, "error": {"message": error} if error else None},
        )

    return _call(go)


@mcp.tool()
def report_issue(
    description: str,
    severity: str = "medium",
    run_id: str | None = None,
    step_key: str | None = None,
    skill_name: str | None = None,
    evidence: dict | None = None,
) -> dict:
    """Report that a step could not be done as described (feeds the improvement loop)."""

    def go():
        return get_client().post_or_queue(
            "/telemetry/issues",
            {
                "description": description,
                "severity": severity,
                "run_id": run_id,
                "step_key": step_key,
                "skill_name": skill_name,
                "evidence": evidence,
            },
        )

    return _call(go)


def sandbox_dir(run_id: str, step_key: str) -> Path:
    return HOME / "sandbox" / run_id / step_key


def _copy_into(src: Path, dest_root: Path) -> Path:
    """Copy a file or folder under dest_root keeping its absolute path as relative structure."""
    rel = Path(*[p for p in src.resolve().parts if p not in ("/", src.resolve().anchor)])
    dest = dest_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return dest


@mcp.tool()
def snapshot(
    run_id: str, step_key: str, paths: list[str] | None = None, refs: list[dict] | None = None, note: str | None = None
) -> dict:
    """Back up what a step is about to change, BEFORE executing it for real.

    `paths`: files or folders copied under ~/.autoskill/sandbox/<run>/<step>/ (restorable with restore_snapshot).
    `refs`: things you cannot copy (e.g. {"kind": "db", "ref": "table invoices, transaction open"}).
    """

    def go():
        items: list[dict] = []
        root = sandbox_dir(run_id, step_key)
        for raw in paths or []:
            src = Path(raw).expanduser()
            if not src.exists():
                items.append({"kind": "missing", "ref": str(src), "note": "did not exist at snapshot time"})
                continue
            dest = _copy_into(src, root)
            items.append(
                {"kind": "folder" if src.is_dir() else "file", "ref": str(src.resolve()), "local_copy": str(dest)}
            )
        for ref in refs or []:
            if isinstance(ref, dict) and ref.get("ref"):
                items.append({"kind": ref.get("kind", "other"), "ref": str(ref["ref"]), "note": ref.get("note")})
        root.mkdir(parents=True, exist_ok=True)
        (root / "snapshot.json").write_text(json.dumps({"items": items, "note": note}, indent=2))
        res = get_client().post(
            "/telemetry/snapshots", {"run_id": run_id, "step_key": step_key, "items": items, "note": note}
        )
        return {**res, "local_dir": str(root)}

    return _call(go)


@mcp.tool()
def restore_snapshot(run_id: str, step_key: str) -> dict:
    """Put back the files/folders saved by `snapshot` for this step, then report a 'restore' checkpoint.

    Call it when the person's decision is `restore`. Non-copyable items (db, mailbox) are listed for you
    to restore with the step's declared strategy; mention what you did in the checkpoint result.
    """

    def go():
        root = sandbox_dir(run_id, step_key)
        manifest = root / "snapshot.json"
        if not manifest.exists():
            return {"error": "no_snapshot", "message": f"nothing saved under {root}"}
        data = json.loads(manifest.read_text())
        restored: list[str] = []
        manual: list[dict] = []
        for item in data.get("items", []):
            copy = item.get("local_copy")
            if copy and Path(copy).exists():
                target = Path(item["ref"])
                if Path(copy).is_dir():
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(copy, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(copy, target)
                restored.append(str(target))
            elif item.get("kind") not in ("file", "folder", "missing"):
                manual.append(item)
        proposal = {"restored": restored, "needs_manual_restore": manual, "note": data.get("note")}
        res = get_client().post(
            "/checkpoints", {"run_id": run_id, "step_key": step_key, "phase": "restore", "proposal": proposal}
        )
        return {**res, "restored": restored, "needs_manual_restore": manual}

    return _call(go)


@mcp.tool()
def get_step_guidance(skill_id: str, step_key: str) -> dict:
    """Latest instruction, corrections and memory notes for a step (use after a 'change' decision)."""
    return _call(lambda: get_client().get(f"/telemetry/guidance/{skill_id}/{step_key}"))


# --- interview: this machine as the executor -------------------------------------------------
#
# AutoSkill runs the interview and the person answers in their browser. What arrives here are the
# turns addressed to the machine: look at a folder, open a workbook, check that something answers.


def _interview(session_key: str | None) -> dict:
    """Headers for an interview call: which session, and which version of this package is asking.

    The server compares the version with what it publishes and can ask us to update before going on.
    """
    key = session_key or _state.get("interview")
    if not key:
        raise ValueError("no interview session: call assist_interview with the key from the browser")
    _state["interview"] = key
    return {"X-AutoSkill-Interview": key, "X-AutoSkill-Client": __version__}


@mcp.tool()
def assist_interview(session_key: str) -> dict:
    """Join an AutoSkill interview as its executor, using the key the person pasted from the browser.

    Returns the first turn. If it is a task, carry it out and send the result with `report_task`.
    """

    def go():
        headers = _interview(session_key)
        return get_client().get("/interviews/turn?wait=0", headers=headers)

    return _call(go)


@mcp.tool()
def await_task(session_key: str | None = None, timeout_s: int = 50, max_wait_s: int = 900) -> dict:
    """Wait for the next turn addressed to this machine.

    Polls in short spells rather than holding one long request: the interview may think for minutes
    while the person answers questions in the browser. Returns a turn, or `{"status": "timeout"}`.
    """

    def go():
        headers = _interview(session_key)
        client = get_client()
        spent = 0
        while spent < max(0, max_wait_s):
            wait = max(0, min(timeout_s, 50))
            turn = client.get(f"/interviews/turn?wait={wait}", headers=headers, timeout=wait + 20)
            if turn.get("status") != "working":
                # includes "update": the agent must act on it before the interview can go on
                return turn
            spent += wait or 1
        return {"status": "timeout", "waited_s": spent}

    return _call(go)


@mcp.tool()
def report_task(
    text: str, session_key: str | None = None, turn_id: int | None = None, attachments: list[dict] | None = None
) -> dict:
    """Report what you found or did. Include the turn_id from the task you are answering."""

    def go():
        headers = _interview(session_key)
        return get_client().post(
            "/interviews/turn",
            {"text": text, "attachments": attachments or [], "turn_id": turn_id},
            headers=headers,
        )

    return _call(go)


@mcp.tool()
def attach_file(path: str, session_key: str | None = None) -> dict:
    """Send a file to the interview; the server summarises it (sheets, headers, first rows).

    Use it when a sample answers better than a description, and pass the returned descriptor in the
    `attachments` list of `report_task`.
    """

    def go():
        headers = _interview(session_key)
        src = Path(path).expanduser()
        if not src.is_file():
            return {"error": "not_a_file", "message": f"{src} does not exist or is not a file"}
        data = src.read_bytes()
        if len(data) > MAX_UPLOAD_BYTES:
            return {"error": "file_too_large", "message": f"{src.name} is {len(data)} bytes", "limit": MAX_UPLOAD_BYTES}
        return get_client().post_file(
            "/interviews/turn/attachments", filename=src.name, content=data, headers=headers
        )

    return _call(go)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = ["json", "main", "mcp"]
