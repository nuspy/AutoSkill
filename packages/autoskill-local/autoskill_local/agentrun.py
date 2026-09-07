"""Asking an agent to do something, instead of asking a person to paste it into one.

Everything else AutoSkill does locally is filesystem work. This is different: it starts somebody's
agent and gives it an instruction, so the rules are stricter and the fallback matters more than the
feature.

Two ways in, and the difference is what the person can see:

* **ACP** — the Agent Client Protocol, JSON-RPC 2.0 over stdio, which is what an editor uses to host
  an agent. It is a session: the agent's turns arrive as notifications while the work is happening,
  so the page can show it rather than waiting for a result. Verified on Hermes 0.21.0.
* **one-shot** — `hermes -z`, `claude -p`, `codex exec`. One prompt, one answer, no session. The work
  happens somewhere the person is not looking, which the page has to say.

And one way out, which is not a failure: **manual**. An agent with neither declared, or not found on
this machine, means the person is handed the instruction to paste — how every agent worked until now,
and how they must keep working.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from typing import Any

from autoskill_local.targets import get_target

Progress = Callable[[str], None]
ACP_PROTOCOL = 1


class AgentUnavailable(Exception):
    """This agent cannot be started here — so the person pastes the instruction, as before."""

    code = "agent_unavailable"


def _argv(target, mode: str, prompt: str) -> list[str]:
    executable = target.executable()
    if executable is None:
        raise AgentUnavailable(f"no {target.display_name} program found on this machine")
    args = target.acp_args if mode == "acp" else target.oneshot_args
    if not args:
        raise AgentUnavailable(f"{target.display_name} has no {mode} mode")
    return [executable, *(a.replace("{prompt}", prompt) for a in args)]


def run_oneshot(target_id: str, prompt: str, *, timeout_s: int = 900, say: Progress | None = None) -> dict[str, Any]:
    """Start the agent with the instruction already in it, and wait for the one answer.

    The session is separate from any the person has open, so the page must say so: the work happens
    where they are not looking, and an agent that asks a question mid-way has nobody to ask.
    """
    target = get_target(target_id)
    argv = _argv(target, "oneshot", prompt)
    if say:
        say(f"starting {target.display_name}")
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return {"mode": "oneshot", "status": "timeout", "timeout_s": timeout_s}
    # Trimmed rather than returned whole: this crosses a native messaging channel with a 1 MB limit,
    # and the useful part of an agent's answer is the end of it.
    tail = (done.stdout or done.stderr or "").strip()[-4000:]
    return {"mode": "oneshot", "status": "ok" if done.returncode == 0 else "failed", "exit": done.returncode, "output": tail}


def run_acp(target_id: str, prompt: str, *, timeout_s: int = 900, say: Progress | None = None) -> dict[str, Any]:
    """Drive the agent over ACP, reporting its turns while they happen.

    The client half of the protocol, kept to the minimum this needs: initialize, open a session, send
    the prompt, relay updates until the turn ends. Anything the agent asks of a client we do not
    implement is answered with a refusal rather than silence — an unanswered request would hang the
    agent, and a hung agent looks exactly like a broken one.
    """
    target = get_target(target_id)
    argv = _argv(target, "acp", prompt)
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
    )
    state: dict[str, Any] = {"turns": [], "replies": {}}
    counter = {"id": 0}

    def send(message: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def request(method: str, params: dict[str, Any]) -> int:
        counter["id"] += 1
        send({"jsonrpc": "2.0", "id": counter["id"], "method": method, "params": params})
        return counter["id"]

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "method" in message and "id" in message:
                # The agent is asking the client for something — permission, a file. We host no
                # editor and grant nothing; refusing is an answer, and silence would hang it.
                send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "not supported"}})
                continue
            if "method" in message:
                update = (message.get("params") or {}).get("update") or {}
                text = _text_of(update)
                if text:
                    state["turns"].append(text)
                    if say:
                        say(text[:400])
                continue
            state["replies"][message.get("id")] = message

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        hello = _await_reply(
            state, request("initialize", {"protocolVersion": ACP_PROTOCOL, "clientCapabilities": {"fs": {}}}), timeout_s=30
        )
        opened = _await_reply(state, request("session/new", {"cwd": str(target.base), "mcpServers": []}), timeout_s=60)
        sid = (opened or {}).get("sessionId")
        if not sid:
            raise AgentUnavailable("the agent opened no session")
        if say:
            say(f"{target.display_name} session open")
        ended = _await_reply(
            state,
            request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": prompt}]}),
            timeout_s=timeout_s,
        )
        return {
            "mode": "acp",
            "status": "ok" if ended is not None else "timeout",
            "stop_reason": (ended or {}).get("stopReason"),
            "turns": state["turns"][-40:],
            "agent": ((hello or {}).get("agentInfo") or {}).get("name"),
        }
    finally:
        proc.kill()


def _text_of(update: dict[str, Any]) -> str:
    """The readable part of a session update, whatever shape this agent sends it in."""
    content = update.get("content")
    if isinstance(content, dict):
        return str(content.get("text") or "")
    if isinstance(content, str):
        return content
    return ""


def _await_reply(state: dict[str, Any], request_id: int, *, timeout_s: int) -> dict[str, Any] | None:
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        reply = state["replies"].get(request_id)
        if reply is not None:
            if "error" in reply:
                raise AgentUnavailable(str(reply["error"].get("message", "the agent refused")))
            return reply.get("result") or {}
        time.sleep(0.05)
    return None


def run(target_id: str, prompt: str, *, mode: str | None = None, timeout_s: int = 900, say: Progress | None = None):
    """Start the agent the best way it supports, and say plainly when it supports none.

    `{"mode": "manual"}` is a real answer, not an error: the page then shows the instruction to paste,
    which is what it did for every agent before any of this existed.
    """
    modes = get_target(target_id).run_modes()
    for candidate in [mode] if mode else modes:
        if candidate not in modes:
            continue
        try:
            return (run_acp if candidate == "acp" else run_oneshot)(target_id, prompt, timeout_s=timeout_s, say=say)
        except (AgentUnavailable, OSError) as exc:
            if say:
                say(f"{candidate} did not work ({exc}); trying the next way")
            continue
    return {"mode": "manual", "status": "unsupported", "prompt": prompt}
