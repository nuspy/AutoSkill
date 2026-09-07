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
