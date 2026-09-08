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
import time
from collections.abc import Callable
from typing import Any

from autoskill_local.targets import get_target

Progress = Callable[[str], None]
ACP_PROTOCOL = 1


class AgentUnavailable(Exception):
    """This agent cannot be started here — so the person pastes the instruction, as before."""

    code = "agent_unavailable"


def _argv(target, mode: str, prompt: str, model: str = "", provider: str = "") -> list[str]:
    executable = target.executable()
    if executable is None:
        raise AgentUnavailable(f"no {target.display_name} program found on this machine")
    args = target.acp_args if mode == "acp" else target.oneshot_args
    if not args:
        raise AgentUnavailable(f"{target.display_name} has no {mode} mode")
    # Override flags are global, so they come before the mode subcommand; an agent that declares no
    # flag for them simply does not get the override rather than being handed an argument it rejects.
    override: list[str] = []
    if model and target.model_flag:
        override += [target.model_flag, model]
    if provider and target.provider_flag:
        override += [target.provider_flag, provider]
    return [executable, *override, *(a.replace("{prompt}", prompt) for a in args)]


def run_oneshot(target_id: str, prompt: str, *, timeout_s: int = 900, say: Progress | None = None,
                model: str = "", provider: str = "") -> dict[str, Any]:
    """Start the agent with the instruction already in it, and wait for the one answer.

    The session is separate from any the person has open, so the page must say so: the work happens
    where they are not looking, and an agent that asks a question mid-way has nobody to ask.
    """
    target = get_target(target_id)
    argv = _argv(target, "oneshot", prompt, model=model, provider=provider)
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


def run_acp(target_id: str, prompt: str, *, timeout_s: int = 900, say: Progress | None = None,
            model: str = "", provider: str = "") -> dict[str, Any]:
    """Drive the agent over ACP, reporting its turns while they happen.

    The client half of the protocol, kept to the minimum this needs: initialize, open a session, send
    the prompt, relay updates until the turn ends. Anything the agent asks of a client we do not
    implement is answered with a refusal rather than silence — an unanswered request would hang the
    agent, and a hung agent looks exactly like a broken one.
    """
    target = get_target(target_id)
    argv = _argv(target, "acp", prompt, model=model, provider=provider)
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
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        reply = state["replies"].get(request_id)
        if reply is not None:
            if "error" in reply:
                raise AgentUnavailable(str(reply["error"].get("message", "the agent refused")))
            return reply.get("result") or {}
        time.sleep(0.05)
    return None


def run(target_id: str, prompt: str, *, mode: str | None = None, timeout_s: int = 900, say: Progress | None = None,
        model: str = "", provider: str = ""):
    """Start the agent the best way it supports, and say plainly when it supports none.

    `{"mode": "manual"}` is a real answer, not an error: the page then shows the instruction to paste,
    which is what it did for every agent before any of this existed. `model`/`provider` override the
    agent's default for this run when it supports it — a trial can then use a model that is actually
    reachable without changing the agent's own configuration.
    """
    modes = get_target(target_id).run_modes()
    for candidate in [mode] if mode else modes:
        if candidate not in modes:
            continue
        try:
            fn = run_acp if candidate == "acp" else run_oneshot
            return fn(target_id, prompt, timeout_s=timeout_s, say=say, model=model, provider=provider)
        except (AgentUnavailable, OSError) as exc:
            if say:
                say(f"{candidate} did not work ({exc}); trying the next way")
            continue
    return {"mode": "manual", "status": "unsupported", "prompt": prompt}


def _nudge_prompt(state: dict[str, Any]) -> str:
    """Turn the server's sync state into an instruction that resumes the run and says: keep going.

    The hint alone names the next call, and an agent handed only that may make it and stop once more.
    The sentence around it is what its own loop keeps dropping between a decision and the next step —
    carry the whole trial to `end_run` without waiting to be told each move. Because a one-shot nudge
    is a fresh process, the run id and the exact next checkpoint are spelled out too.
    """
    run_id = state.get("run_id") or ""
    step = state.get("next_step_key") or ""
    phase = state.get("next_phase") or ""
    where = ""
    if run_id:
        # A one-shot nudge is a fresh agent process with none of the earlier turn's memory, so it must
        # be told the run it is resuming and the exact checkpoint to send — otherwise it cannot address
        # the companion tools at all. `start_run` was already called; it must not be called again.
        where = (
            f"You are resuming AutoSkill run_id='{run_id}'. Do NOT call `start_run` again. "
            f"The next checkpoint is phase='{phase}' for step '{step}'. "
        )
    return (
        "You are partway through an AutoSkill trial and your last turn ended early, before the run was "
        f"finished. Do not start over, do not ask the user anything, and do not repeat a decided step. {where}"
        f"{state.get('next_hint', '').strip()} After each checkpoint call `await_decision` and obey the "
        "decision, then go straight on to the next phase or step. Keep going on your own and do not end "
        "your turn until you have called `end_run`."
    )


def drive_trial(
    target_id: str,
    prompt: str,
    *,
    poll: Callable[[], dict[str, Any]],
    invoke: Callable[[str], dict[str, Any]] | None = None,
    say: Progress | None = None,
    max_nudges: int = 12,
    max_stalls: int = 2,
    human_wait_s: float = 1800.0,
    poll_interval_s: float = 3.0,
    model: str = "",
    provider: str = "",
) -> dict[str, Any]:
    """Run a trial to the end, re-nudging the agent whenever its own loop stops between steps.

    A trial is a long conversation with pauses for a person's decision, and some agents end their turn
    at the first pause instead of resuming after it — leaving the trial page waiting for a step that is
    never sent. The server is kept as the one authority on where the trial stands (`poll` reads its
    `/sync`), and each time the agent falls silent while it is still the agent's turn it is handed the
    server's own `next_hint`.

    The driver never acts for the person: a checkpoint still `pending` is theirs to decide, and here it
    only waits. It ends when the run does (`end_run`), when a nudge stops making progress (a genuinely
    stuck agent, handed back), or when a decision never comes. `poll` returns the `agent` block of the
    sync response; `invoke` runs the agent once and returns when its turn ends (the real one blocks in
    `run`, so control comes back only when the agent is idle — which is exactly when we may look).
    """
    # One-shot, not ACP, for a trial. Two reasons, both learned the hard way: a per-run model override
    # (`-m`/`--provider`) is honoured in one-shot but ignored in ACP, so a trial can be pointed at a
    # model that is actually reachable; and one-shot loads the agent's own configuration, which is
    # where the companion MCP tools live, while the ACP session this client opens declares none. The
    # trial page stays watchable regardless, because the checkpoints are what it shows.
    do = invoke or (lambda text: run(target_id, text, say=say, mode="oneshot", model=model, provider=provider))
    last_agent: dict[str, Any] | None = None

    def drive(text: str) -> dict[str, Any]:
        nonlocal last_agent
        last_agent = do(text)
        return last_agent

    nudges = stalls = 0
    waited = 0.0
    started_agent = False  # whether we have already sent the start instruction this drive
    # A sentinel, because `None` is itself a real value here (a run open with no checkpoint yet); this
    # says "no nudge is waiting to be judged" and keeps the two apart.
    unresolved = object()
    pending_cp: Any = unresolved
    while True:
        state = poll()
        if not state.get("run_open"):
            if not state.get("started"):
                # No run yet. Launch the trial once; if the next look still shows nothing started, the
                # agent never called `start_run` and re-launching would only repeat that.
                if started_agent:
                    # The agent ran but never called `start_run`. That is almost always the agent
                    # failing before it could — most often it could not reach its own model — so the
                    # reason it printed is the useful thing to hand back, not a bare "not started".
                    return {"mode": "trial_driver", "status": "not_started", "nudges": nudges,
                            "agent": _agent_reason(last_agent)}
                started_agent = True
                if say:
                    say("starting the trial in your agent")
                drive(prompt)
                continue
            return {"mode": "trial_driver", "status": "completed", "nudges": nudges,
                    "run_status": state.get("run_status")}
        cp = state.get("last_checkpoint_id")
        if pending_cp is not unresolved:
            # Judge the nudge we just sent: a new checkpoint (id moved) or the person's turn now is
            # progress; the same decided checkpoint means the nudge did nothing.
            progressed = cp != pending_cp or bool(state.get("waiting_on_human"))
            stalls = 0 if progressed else stalls + 1
            pending_cp = unresolved  # type: ignore[assignment]
        if state.get("waiting_on_human"):
            if waited >= human_wait_s:
                return {"mode": "trial_driver", "status": "waiting_on_human", "nudges": nudges}
            # A heartbeat every ~15s, not just once: the progress keeps the browser's native-messaging
            # channel warm so the extension's service worker is not shut down mid-wait, and tells the
            # person the driver is still there while they think.
            if say and (waited % 15.0) < poll_interval_s:
                say("waiting for the person to decide the current step")
            time.sleep(poll_interval_s)
            waited += poll_interval_s
            continue
        waited = 0.0
        hint = state.get("next_hint")
        if not hint:
            time.sleep(poll_interval_s)
            continue
        if nudges >= max_nudges or stalls >= max_stalls:
            return {"mode": "trial_driver", "status": "stuck", "nudges": nudges, "next_hint": hint,
                    "agent": _agent_reason(last_agent)}
        nudges += 1
        pending_cp = cp
        if say:
            say(f"agent stopped early — nudging it to {state.get('next_phase')} of {state.get('next_step_key')}")
        drive(_nudge_prompt(state))


def _agent_reason(result: dict[str, Any] | None) -> dict[str, Any]:
    """A short, honest account of what the agent last did — for a driver result that stalled.

    The agent's own words are what explain a trial that would not start: `run` keeps the last turns
    and the one-shot output, and when the model was unreachable that text is exactly the message the
    person needs ("API call failed... Connection error"), not a bare "not started". Kept small: this
    crosses the native-messaging channel and only the tail of the agent's output carries the reason.
    """
    if not result:
        return {"mode": "none", "note": "the agent was never started"}
    turns = result.get("turns") or []
    tail = (turns[-1] if turns else result.get("output") or "").strip()
    return {
        "mode": result.get("mode"),
        "status": result.get("status"),
        "stop_reason": result.get("stop_reason"),
        "last_output": tail[-600:],
    }
