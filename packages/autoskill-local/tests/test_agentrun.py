"""Starting somebody's agent, and the fallback that matters more than the feature.

Everything else AutoSkill does locally is filesystem work; this hands an instruction to a program the
person trusts with their files. So what is tested here is mostly what it refuses to do, and that an
agent it cannot start produces a sentence to paste rather than an error.

The capabilities were verified on a real machine before being declared:
`hermes acp --check` answers OK and the ACP handshake returns hermes-agent 0.21.0; `hermes -z`,
`claude -p` and `codex exec` each answered a one-word prompt.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from autoskill_local import agentrun
from autoskill_local.targets import get_target
from autoskill_local.targets.base import LocalTarget


def test_the_command_line_comes_from_the_adapter_not_the_request(monkeypatch, tmp_path):
    """The agent is chosen by id; nothing in a request names a program or its arguments."""
    monkeypatch.setattr(LocalTarget, "executable", lambda _self: "/usr/bin/hermes")
    argv = agentrun._argv(get_target("hermes"), "oneshot", "do the thing")
    assert argv == ["/usr/bin/hermes", "-z", "do the thing"]
    assert agentrun._argv(get_target("hermes"), "acp", "ignored") == ["/usr/bin/hermes", "acp"]


def test_an_agent_that_is_not_installed_here_says_so(monkeypatch):
    monkeypatch.setattr(LocalTarget, "executable", lambda _self: None)
    with pytest.raises(agentrun.AgentUnavailable, match="no .* program"):
        agentrun._argv(get_target("hermes"), "oneshot", "x")


def test_an_agent_with_no_declared_mode_is_never_guessed_at(monkeypatch):
    """OpenClaw and Antigravity declare nothing because nothing was verified for them.

    Guessing would launch the wrong program on somebody's machine, which is worse than asking them
    to paste a sentence.
    """
    monkeypatch.setattr(LocalTarget, "executable", lambda _self: "/usr/bin/whatever")
    assert get_target("openclaw").run_modes() == []
    assert get_target("antigravity").run_modes() == []
    with pytest.raises(agentrun.AgentUnavailable, match="no oneshot mode"):
        agentrun._argv(get_target("openclaw"), "oneshot", "x")


def test_when_nothing_can_be_started_the_instruction_comes_back_to_be_pasted(monkeypatch):
    monkeypatch.setattr(LocalTarget, "run_modes", lambda _self: [])
    assert agentrun.run("hermes", "do the thing") == {
        "mode": "manual",
        "status": "unsupported",
        "prompt": "do the thing",
    }


def test_a_mode_that_fails_falls_through_to_the_next_one(monkeypatch):
    """ACP is preferred because its turns can be watched; a machine where it fails still works."""
    said: list[str] = []
    monkeypatch.setattr(LocalTarget, "run_modes", lambda _self: ["acp", "oneshot"])
    monkeypatch.setattr(agentrun, "run_acp", lambda *a, **k: (_ for _ in ()).throw(OSError("no pipe")))
    monkeypatch.setattr(agentrun, "run_oneshot", lambda *a, **k: {"mode": "oneshot", "status": "ok"})

    result = agentrun.run("hermes", "x", say=said.append)

    assert result["mode"] == "oneshot"
    assert any("did not work" in line for line in said), "and the person is told which way was tried"


def test_a_one_shot_that_never_returns_is_reported_rather_than_waited_on(monkeypatch):
    def hang(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="hermes", timeout=1)

    monkeypatch.setattr(LocalTarget, "executable", lambda _self: "/usr/bin/hermes")
    monkeypatch.setattr(agentrun.subprocess, "run", hang)
    assert agentrun.run_oneshot("hermes", "x", timeout_s=1) == {
        "mode": "oneshot",
        "status": "timeout",
        "timeout_s": 1,
    }


def test_the_answer_is_trimmed_because_it_crosses_a_bounded_channel(monkeypatch):
    """Native messaging refuses more than a megabyte, and the useful part of an answer is the end."""
    monkeypatch.setattr(LocalTarget, "executable", lambda _self: "/usr/bin/hermes")
    monkeypatch.setattr(
        agentrun.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="x" * 50_000, stderr=""),
    )
    out = agentrun.run_oneshot("hermes", "x")["output"]
    assert len(out) == 4000 and out.endswith("x")


def test_a_failing_one_shot_reports_its_exit_code_and_what_it_said(monkeypatch):
    monkeypatch.setattr(LocalTarget, "executable", lambda _self: "/usr/bin/hermes")
    monkeypatch.setattr(
        agentrun.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 3, stdout="", stderr="model unavailable"),
    )
    result = agentrun.run_oneshot("hermes", "x")
    assert result["status"] == "failed" and result["exit"] == 3
    assert "model unavailable" in result["output"], "the reason, not just that it failed"


def test_the_readable_part_of_a_turn_is_found_whatever_shape_it_arrives_in():
    assert agentrun._text_of({"content": {"type": "text", "text": "hello"}}) == "hello"
    assert agentrun._text_of({"content": "hello"}) == "hello"
    assert agentrun._text_of({"content": {"type": "image"}}) == ""
    assert agentrun._text_of({}) == ""


class _FakeAgent:
    """An ACP agent in a few lines: enough to prove the client half without launching anything."""

    def __init__(self, script):
        self.script = script
        self.written: list[dict] = []
        self.lines: list[str] = []
        self.stdin = self
        self.stdout = self
        self.killed = False

    def write(self, text):  # stdin
        message = json.loads(text)
        self.written.append(message)
        for reply in self.script.get(message.get("method"), []):
            is_reply = "method" not in reply and "id" not in reply
            self.lines.append(json.dumps({**reply, **({"id": message["id"]} if is_reply else {})}))

    def flush(self):
        pass

    def __iter__(self):  # stdout
        # Blocks like a real pipe instead of ending as soon as the queue empties: the client writes
        # its next request only after reading the previous reply, so a generator that stopped at the
        # first gap would end the conversation after `initialize`.
        import time

        while not self.killed:
            if self.lines:
                yield self.lines.pop(0)
            else:
                time.sleep(0.01)

    def kill(self):
        self.killed = True


def test_acp_opens_a_session_sends_the_prompt_and_relays_the_turns(monkeypatch):
    agent = _FakeAgent(
        {
            "initialize": [{"jsonrpc": "2.0", "result": {"agentInfo": {"name": "fake"}}}],
            "session/new": [{"jsonrpc": "2.0", "result": {"sessionId": "s1"}}],
            "session/prompt": [
                {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"content": {"text": "working"}}}},
                {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}},
            ],
        }
    )
    monkeypatch.setattr(LocalTarget, "executable", lambda _self: "/usr/bin/hermes")
    monkeypatch.setattr(agentrun.subprocess, "Popen", lambda *a, **k: agent)
    said: list[str] = []

    result = agentrun.run_acp("hermes", "do the thing", timeout_s=10, say=said.append)

    assert result["status"] == "ok" and result["stop_reason"] == "end_turn"
    assert result["turns"] == ["working"], "the turn arrived while the work was happening"
    assert "working" in said
    methods = [m.get("method") for m in agent.written if "method" in m]
    assert methods == ["initialize", "session/new", "session/prompt"]
    assert agent.killed, "the process is not left running behind the answer"


def test_a_request_from_the_agent_is_refused_rather_than_ignored(monkeypatch):
    """We host no editor and grant nothing. Silence would hang the agent, and a hung agent looks
    exactly like a broken one."""
    agent = _FakeAgent(
        {
            "initialize": [{"jsonrpc": "2.0", "result": {}}],
            "session/new": [
                {"jsonrpc": "2.0", "result": {"sessionId": "s1"}},
                {"jsonrpc": "2.0", "id": 99, "method": "fs/readTextFile", "params": {"path": "/etc/passwd"}},
            ],
            "session/prompt": [{"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}}],
        }
    )
    monkeypatch.setattr(LocalTarget, "executable", lambda _self: "/usr/bin/hermes")
    monkeypatch.setattr(agentrun.subprocess, "Popen", lambda *a, **k: agent)

    agentrun.run_acp("hermes", "x", timeout_s=10)

    refusals = [m for m in agent.written if m.get("id") == 99 and "error" in m]
    assert refusals, "the agent's request was answered, and answered no"


# --- driving a trial past an agent that stops between steps ------------------------------------


def _drive(states, *, prompt="use the skill and follow the protocol", **kw):
    """Run drive_trial over a scripted sequence of `/sync` agent-blocks, recording each agent call."""
    seq = iter(states)
    calls: list[str] = []
    result = agentrun.drive_trial(
        "hermes",
        prompt,
        poll=lambda: next(seq),
        invoke=lambda text: calls.append(text) or {"mode": "fake"},
        poll_interval_s=0.0,
        human_wait_s=1.0,
        **kw,
    )
    return result, calls


def test_a_fresh_trial_is_started_then_nudged_to_the_end():
    """The agent stops after each decision; the driver starts it, then hands it the next step until
    the run closes."""
    result, calls = _drive(
        [
            {"run_open": False, "started": False},  # first look: nothing has started
            {"run_open": True, "started": True, "waiting_on_human": False,
             "next_hint": "Send checkpoint phase='preview'", "next_phase": "preview",
             "next_step_key": "s1", "last_checkpoint_id": "cp1"},
            {"run_open": True, "started": True, "waiting_on_human": False,
             "next_hint": "Send checkpoint phase='execute'", "next_phase": "execute",
             "next_step_key": "s1", "last_checkpoint_id": "cp2"},
            {"run_open": False, "started": True, "run_status": "succeeded"},
        ]
    )
    assert result["status"] == "completed" and result["nudges"] == 2
    assert calls[0] == "use the skill and follow the protocol", "the first turn is the start instruction"
    assert "Send checkpoint phase='preview'" in calls[1], "then the server's own next hint"
    assert "do not end your turn until you have called `end_run`" in calls[1]


def test_a_trial_already_running_is_resumed_without_being_restarted():
    """A run is already open: the driver must not send `start_run` again, only nudge on."""
    result, calls = _drive(
        [
            {"run_open": True, "started": True, "waiting_on_human": False,
             "next_hint": "Send checkpoint phase='preview'", "last_checkpoint_id": "cp1"},
            {"run_open": False, "started": True, "run_status": "succeeded"},
        ]
    )
    assert result["status"] == "completed" and result["nudges"] == 1
    assert all("use the skill" not in c for c in calls), "the start instruction is never sent"
    assert len(calls) == 1 and "phase='preview'" in calls[0]


def test_a_checkpoint_awaiting_the_person_is_left_alone():
    """A pending checkpoint is the person's to decide; nudging would only raise it twice."""
    result, calls = _drive(
        [
            {"run_open": False, "started": False},
            {"run_open": True, "started": True, "waiting_on_human": True, "last_checkpoint_id": "cp1"},
            {"run_open": True, "started": True, "waiting_on_human": False,
             "next_hint": "Send checkpoint phase='execute'", "last_checkpoint_id": "cp1"},
            {"run_open": False, "started": True, "run_status": "succeeded"},
        ]
    )
    assert result["status"] == "completed"
    assert result["nudges"] == 1, "no nudge while it was the person's turn, one after they decided"
    assert calls[0].startswith("use the skill"), "start"
    assert "phase='execute'" in calls[1]


def test_an_agent_that_a_nudge_never_moves_is_handed_back():
    """When a nudge produces no new checkpoint twice over, the agent is genuinely stuck: stop prodding
    it and return, so a person can step in rather than watch it loop."""
    stuck = {"run_open": True, "started": True, "waiting_on_human": False,
             "next_hint": "Send checkpoint phase='preview'", "last_checkpoint_id": "cp1"}
    result, _ = _drive([{"run_open": False, "started": False}, stuck, stuck, stuck])
    assert result["status"] == "stuck" and result["nudges"] == 2
    assert result["next_hint"] == "Send checkpoint phase='preview'"


# --- preferring the model already loaded in a local engine -------------------------------------


def test_the_model_loaded_in_lm_studio_is_preferred_over_the_configured_default(monkeypatch):
    """The person picks the model by loading it: a run should use what is in memory, not force a
    reload of a smaller configured default."""
    monkeypatch.setattr(LocalTarget, "local_providers", lambda _self: [("lmstudio", "http://127.0.0.1:1300/v1")])

    class _Resp:
        def __init__(self, data): self._data = data
        def json(self): return {"data": self._data}

    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: _Resp([{"id": "qwen-35b", "state": "loaded"}]))
    assert agentrun._autodetect_loaded_model(get_target("hermes")) == ("lmstudio", "qwen-35b")


def test_nothing_loaded_falls_back_to_the_configured_default(monkeypatch):
    monkeypatch.setattr(LocalTarget, "local_providers", lambda _self: [("lmstudio", "http://127.0.0.1:1300/v1")])
    import httpx

    def down(*a, **k):
        raise httpx.ConnectError("engine is down")

    monkeypatch.setattr(httpx, "get", down)
    assert agentrun._autodetect_loaded_model(get_target("hermes")) is None


def test_run_keeps_the_agents_own_model_by_default(monkeypatch):
    """Default: no override. The agent runs on its own configured model, so it is not forced onto a
    small local one that would re-prefill its whole tool list every turn."""
    monkeypatch.delenv("AUTOSKILL_TRIAL_USE_LOADED_MODEL", raising=False)
    monkeypatch.setattr(LocalTarget, "run_modes", lambda _self: ["oneshot"])
    called = {"auto": False}
    monkeypatch.setattr(agentrun, "_autodetect_loaded_model",
                        lambda _t: called.update(auto=True) or ("lmstudio", "qwen-35b"))
    seen = {}
    monkeypatch.setattr(agentrun, "run_oneshot",
                        lambda tid, prompt, **kw: seen.update(kw) or {"mode": "oneshot", "status": "ok"})
    agentrun.run("hermes", "do it")
    assert seen.get("model") == "" and seen.get("provider") == "", "no model override without the opt-in"
    assert called["auto"] is False, "autodetect is not even consulted by default"


def test_run_uses_the_loaded_model_when_opted_in(monkeypatch):
    monkeypatch.setenv("AUTOSKILL_TRIAL_USE_LOADED_MODEL", "1")
    monkeypatch.setattr(LocalTarget, "run_modes", lambda _self: ["oneshot"])
    monkeypatch.setattr(agentrun, "_autodetect_loaded_model", lambda _t: ("lmstudio", "qwen-35b"))
    seen = {}
    monkeypatch.setattr(agentrun, "run_oneshot",
                        lambda tid, prompt, **kw: seen.update(kw) or {"mode": "oneshot", "status": "ok"})
    agentrun.run("hermes", "do it")
    assert seen.get("model") == "qwen-35b" and seen.get("provider") == "lmstudio"


def test_an_explicit_model_is_not_overridden_by_autodetection(monkeypatch):
    monkeypatch.setattr(LocalTarget, "run_modes", lambda _self: ["oneshot"])
    called = {"auto": False}
    monkeypatch.setattr(agentrun, "_autodetect_loaded_model",
                        lambda _t: called.update(auto=True) or ("lmstudio", "qwen-35b"))
    monkeypatch.setattr(agentrun, "run_oneshot", lambda tid, prompt, **kw: {"model": kw.get("model")})
    res = agentrun.run("hermes", "do it", model="gpt-5", provider="openai")
    assert res["model"] == "gpt-5" and called["auto"] is False, "an explicit choice wins, and autodetect is skipped"


def test_a_closed_run_with_a_gap_starts_a_fresh_run_to_retry():
    """A previous run ended with a step unconfirmed (`needs_new_run`): the driver launches a new run
    that resumes at the gap, rather than reporting the trial complete."""
    result, calls = _drive([
        {"run_open": False, "started": True, "needs_new_run": True, "next_step_key": "step2"},  # retry needed
        {"run_open": True, "started": True, "waiting_on_human": False,
         "next_hint": "Send checkpoint phase='preview'", "next_step_key": "step2", "last_checkpoint_id": "cp1"},
        {"run_open": False, "started": True, "run_status": "succeeded"},  # gap closed
    ])
    assert result["status"] == "completed"
    assert len(calls) >= 1 and calls[0].startswith("use the skill"), "it launched the agent to retry"


def test_a_closed_run_with_no_gap_is_complete_not_retried():
    result, calls = _drive([{"run_open": False, "started": True, "run_status": "succeeded"}])
    assert result["status"] == "completed" and calls == [], "nothing to retry: no agent launched"
