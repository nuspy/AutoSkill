"""The browser's way in: a native messaging host that drives the same functions the CLI commands do.

A browser extension cannot write to `~/.hermes/skills/` and cannot start a process. That is the
sandbox, not a gap in an API, and no permission opens it. What it can do is launch *this* — an
executable the browser starts and talks to over stdin and stdout — which is why the extension does
not replace `autoskill-local` but drives it.

The protocol is Chrome's: each message is four bytes of little-endian length followed by UTF-8 JSON.
A request is `{"id", "op", "params"}`; the answers are `{"id", "kind": "progress"|"result"|"error"}`,
several per request, because installing takes a while and a page that cannot say how far it has got
is a page that looks broken.

Two rules hold this thing together, and both exist because a native messaging host is a hole straight
through the browser's sandbox:

* **A closed set of operations.** Nothing here takes a shell command, an arbitrary path to write, or
  a URL to execute. `OPS` is the whole surface.
* **A caller allow-list.** Chrome passes the calling extension's origin as `argv[1]`; anything that is
  not an extension we shipped is refused before a single operation runs.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import traceback
from collections.abc import Callable, Iterator
from typing import Any, BinaryIO

from autoskill_local import __version__

PROTOCOL = 1
# Chrome refuses to send a host more than this, and will not read back an oversized reply either.
MAX_MESSAGE = 1024 * 1024
_HEADER = struct.Struct("<I")

# The extension we ship. Its id is stable because the manifest pins a `key`; without that it would
# change on every machine and this list could not be written at all. `AUTOSKILL_ALLOWED_EXTENSIONS`
# (comma-separated ids) exists for developing against an unpacked copy, and is a development door:
# it widens who may drive this machine, so it is read once, at start, and never from a message.
EXTENSION_IDS = ("cnkodldlkekifpmakgkkmpdikbobbjff",)


def allowed_origins() -> set[str]:
    extra = [x.strip() for x in os.environ.get("AUTOSKILL_ALLOWED_EXTENSIONS", "").split(",") if x.strip()]
    return {f"chrome-extension://{i}/" for i in (*EXTENSION_IDS, *extra)}


def origin_allowed(origin: str | None) -> bool:
    """Chrome hands the caller's origin as argv[1]; anything else has no business here.

    Chrome checks this too, against the host manifest. Checking again is not redundancy for its own
    sake: the manifest is a file on the person's disk that anything running as them could rewrite,
    while this list ships with the code.
    """
    permitted = allowed_origins()
    if not permitted:
        # Nothing is allowed yet rather than everything: an empty allow-list that means "let anyone
        # in" is how a hole like this gets left open by accident.
        return False
    return bool(origin) and origin.rstrip("/") + "/" in permitted


class LocalRefusal(Exception):
    """A request this host will not carry out, named so the page can say why."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.details: dict[str, Any] = {}
        super().__init__(message)


def _url(params: dict[str, Any], field: str) -> str:
    """A download address, accepted only if it belongs to the server this machine is connected to.

    The page names the manifest, and the page is not the authority on where this machine may fetch
    from: a compromised or merely wrong page could otherwise have the host install from anywhere. The
    configured `server_url` is the authority, because a person put it there with `autoskill login`.
    """
    from autoskill_local.cli import _cfg

    value = params.get(field)
    if not isinstance(value, str) or not value:
        raise LocalRefusal("url_required", f"{field} is missing")
    server = (_cfg().server_url or "").rstrip("/")
    if not server:
        raise LocalRefusal("not_logged_in", "this machine is not connected to an AutoSkill server")
    if not value.startswith(server + "/"):
        raise LocalRefusal("foreign_url", f"{field} is not on {server}")
    return value


# --- framing ------------------------------------------------------------------------------------


def encode(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return _HEADER.pack(len(body)) + body


def read_messages(stream: BinaryIO) -> Iterator[dict[str, Any]]:
    """Yield each message on the stream, stopping cleanly when the browser closes it.

    A short read is the end of the conversation, not an error: the browser closes the pipe when the
    extension is disabled, the tab goes away or the browser quits, and all three are ordinary.
    """
    while True:
        header = stream.read(4)
        if len(header) < 4:
            return
        (length,) = _HEADER.unpack(header)
        if length > MAX_MESSAGE:
            raise ValueError(f"message of {length} bytes exceeds the {MAX_MESSAGE} limit")
        body = stream.read(length)
        if len(body) < length:
            return
        yield json.loads(body.decode("utf-8"))


# --- operations ---------------------------------------------------------------------------------


def op_hello(_params: dict[str, Any], _say: Callable[[str], None]) -> dict[str, Any]:
    """What is on the other end, so the page can decide whether it can talk to it."""
    return {"protocol": PROTOCOL, "cli_version": __version__, "ops": sorted(OPS)}


def op_state(_params: dict[str, Any], _say: Callable[[str], None]) -> dict[str, Any]:
    """This machine: the server it answers to, every known agent, the open trials."""
    from autoskill_local.cli import machine_state

    return machine_state()


def op_needs(params: dict[str, Any], _say: Callable[[str], None]) -> dict[str, Any]:
    """Which environment values an install will ask for, before it starts.

    A terminal can be prompted halfway through an installation. A page cannot: it has to ask while the
    person is still looking at it, which means reading the manifest rather than finding out by
    starting something that then stops with nowhere to put the question.
    """
    from autoskill_local.cli import fetch_json, required_env

    manifest = fetch_json(_url(params, "manifest_url"))
    return {"env": required_env(manifest), "skill": (manifest.get("skill") or {}).get("name")}


def op_trial_install(params: dict[str, Any], say: Callable[[str], None]) -> dict[str, Any]:
    from autoskill_local.cli import _cfg, env_from, install_trial_bundle

    token = params.get("token")
    if not token:
        raise LocalRefusal("token_required", "a trial install needs the trial token from the page")
    return install_trial_bundle(
        _cfg(),
        _url(params, "manifest_url"),
        token,
        target=params.get("target"),
        session=params.get("session"),
        env_provider=env_from(params.get("env") or {}),
        progress=say,
    )


def op_install(params: dict[str, Any], say: Callable[[str], None]) -> dict[str, Any]:
    """A permanent installation, from the same manifest the page is showing."""
    from autoskill_local.cli import (
        _cfg,
        _install_from_manifest,
        _register_installation,
        env_from,
        fetch_json,
    )

    cfg = _cfg()
    manifest = fetch_json(_url(params, "manifest_url"))
    target = params.get("target") or manifest.get("default_target")
    if not target:
        raise LocalRefusal("target_required", "this bundle names no agent, so one has to be chosen")
    folder, _meta, record = _install_from_manifest(
        cfg, manifest, target, None, env_provider=env_from(params.get("env") or {}), progress=say
    )
    version_id = (manifest.get("skill") or {}).get("version_id")
    key = f"{target}:{folder}"
    cfg.installs[key] = {**record, "version_id": version_id}
    if cfg.api_key and version_id:
        cfg.installs[key]["installation_id"] = _register_installation(cfg, version_id, target, "extension", say)
    cfg.save()
    return {"skill": folder, "target": target, "version": (manifest.get("skill") or {}).get("version")}


def op_trial_settle(params: dict[str, Any], say: Callable[[str], None]) -> dict[str, Any]:
    """Accept or remove a trial: report the outcome, then settle the copy on this machine."""
    from autoskill_local.cli import _cfg, _finish_trial, _report_outcome, _trial_record

    session = params.get("session")
    outcome = params.get("outcome")
    if not session or outcome not in ("accepted", "removed", "changes_requested", "major_rework"):
        raise LocalRefusal("bad_outcome", "give a session and one of accepted/removed/changes_requested/major_rework")
    cfg = _cfg()
    info = _trial_record(cfg, session, params.get("token"))
    keep = bool(params.get("keep")) and outcome == "accepted"
    keep = _report_outcome(cfg, session, info["token"], outcome, keep)
    _finish_trial(cfg, session, keep, say)
    return {"session": session, "outcome": outcome, "kept": keep}


def op_remove(params: dict[str, Any], say: Callable[[str], None]) -> dict[str, Any]:
    """Remove a permanently installed skill, and tell the server it is gone."""
    from autoskill_local.cli import _cfg, _remove_bundle_parts, _report_removal, get_target

    skill, target = params.get("skill"), params.get("target")
    if not skill or not target:
        raise LocalRefusal("skill_and_target_required", "say which skill, on which agent")
    cfg = _cfg()
    manifest = cfg.installs.pop(f"{target}:{skill}", None) or {}
    t = get_target(target)
    t.remove_skill(skill, manifest)
    _remove_bundle_parts(t, manifest)
    _report_removal(cfg, manifest, target, say)
    cfg.save()
    say(f"{skill} removed from {t.display_name}")
    return {"skill": skill, "target": target}


def op_assistant(params: dict[str, Any], say: Callable[[str], None]) -> dict[str, Any]:
    """Install the `autoskill` skill, which teaches an agent what to do with AutoSkill at all."""
    from autoskill_local.cli import _cfg, _extract_zip, _single_root, detect_targets, fetch_url, get_target

    cfg = _cfg()
    if not cfg.server_url:
        raise LocalRefusal("not_logged_in", "this machine is not connected to an AutoSkill server")
    root = _single_root(_extract_zip(fetch_url(f"{cfg.server_url.rstrip('/')}/dl/skill/autoskill.zip")))
    installed = []
    for target in [params["target"]] if params.get("target") else detect_targets():
        info = get_target(target).install_skill(root, root.name)
        say(f"autoskill installed for {target}")
        installed.append({"target": target, "skill_dir": info["skill_dir"]})
    return {"installed": installed}


def op_agent_run(params: dict[str, Any], say: Callable[[str], None]) -> dict[str, Any]:
    """Ask an agent on this machine to carry out an instruction the page composed.

    The instruction is text, and text is all it is: this starts the agent the person already trusts
    with their files and hands it a sentence, exactly as they would by pasting it. What it does not
    do is take a program to run — the agent is chosen by id from the adapters, never named by the
    page — which is the difference between this and a remote shell.
    """
    from autoskill_local import agentrun
    from autoskill_local.cli import _cfg
    from autoskill_local.client import Client

    prompt = params.get("prompt")
    target = params.get("target")
    if not isinstance(prompt, str) or not prompt.strip():
        raise LocalRefusal("prompt_required", "there is nothing to ask the agent")
    if not target:
        raise LocalRefusal("target_required", "say which agent should do it")
    # Optional per-run model override, so a trial can name a model that is actually reachable (a local
    # one) without changing the agent's own default. The page passes an id, never a program to run.
    model = str(params.get("agent_model") or "")
    provider = str(params.get("agent_provider") or "")

    # A trial is not one instruction but a walkthrough with pauses, and some agents stop at the first
    # pause. When the page names the trial, drive it: start it, then re-nudge the agent past each
    # decision until `end_run`. The trial token is not taken from the page — it is the one this machine
    # already holds from installing the trial, so a page cannot borrow another trial's authority.
    trial_id = params.get("trial_id")
    if trial_id:
        cfg = _cfg()
        if not cfg.server_url:
            raise LocalRefusal("not_logged_in", "this machine is not connected to an AutoSkill server")
        token = ((cfg.trials or {}).get(trial_id) or {}).get("token")
        if not token:
            raise LocalRefusal("unknown_trial", "this machine has no token for that trial — install the trial first")
        client = Client(cfg.server_url, trial_token=token)

        def poll() -> dict[str, Any]:
            return (client.get(f"/trials/{trial_id}/sync") or {}).get("agent") or {}

        return agentrun.drive_trial(
            target, prompt, poll=poll, say=say,
            max_nudges=int(params.get("max_nudges") or 12), model=model, provider=provider,
        )

    return agentrun.run(
        target, prompt, mode=params.get("mode"), timeout_s=int(params.get("timeout_s") or 900),
        say=say, model=model, provider=provider,
    )


def op_agents(_params: dict[str, Any], _say: Callable[[str], None]) -> dict[str, Any]:
    """Which agents this machine can actually start, and how — so the page offers only what works."""
    from autoskill_local.targets import TARGETS, get_target

    return {
        "agents": [
            {"id": tid, "display_name": get_target(tid).display_name, "modes": get_target(tid).run_modes()}
            for tid in TARGETS
        ]
    }


# Each one writes to the person's machine, so each is named here and nowhere else: there is no
# operation that takes a command to run, a path to write or an address to fetch from outside the
# server this machine is connected to.
OPS: dict[str, Callable[[dict[str, Any], Callable[[str], None]], dict[str, Any]]] = {
    "hello": op_hello,
    "state": op_state,
    "needs": op_needs,
    "install": op_install,
    "trial_install": op_trial_install,
    "trial_settle": op_trial_settle,
    "remove": op_remove,
    "assistant": op_assistant,
    "agents": op_agents,
    "agent_run": op_agent_run,
}


# --- the loop -----------------------------------------------------------------------------------


def handle(request: dict[str, Any], send: Callable[[dict[str, Any]], None]) -> None:
    """Run one request, reporting progress and ending in exactly one result or one error."""
    rid = request.get("id")
    op = request.get("op")
    fn = OPS.get(op) if isinstance(op, str) else None
    if fn is None:
        send({"id": rid, "kind": "error", "code": "unknown_op", "message": f"no operation {op!r}", "ops": sorted(OPS)})
        return
    try:
        result = fn(request.get("params") or {}, lambda line: send({"id": rid, "kind": "progress", "message": line}))
        send({"id": rid, "kind": "result", "result": result})
    except Exception as exc:  # noqa: BLE001 - one failed request must not end the conversation
        send(
            {
                "id": rid,
                "kind": "error",
                "code": getattr(exc, "code", exc.__class__.__name__),
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
        )
        print(traceback.format_exc(), file=sys.stderr)


def serve(stdin: BinaryIO, stdout: BinaryIO, origin: str | None) -> int:
    if not origin_allowed(origin):
        stdout.write(encode({"kind": "error", "code": "origin_not_allowed", "message": f"refused {origin!r}"}))
        stdout.flush()
        return 1

    def send(message: dict[str, Any]) -> None:
        stdout.write(encode(message))
        stdout.flush()

    for request in read_messages(stdin):
        handle(request, send)
    return 0


def main() -> None:
    # Binary, unbuffered: the framing is bytes, and on Windows a text-mode stdout would translate
    # newlines inside a length-prefixed body and corrupt every message that contained one.
    raise SystemExit(serve(sys.stdin.buffer, sys.stdout.buffer, sys.argv[1] if len(sys.argv) > 1 else None))


if __name__ == "__main__":  # `python -m autoskill_local.nativehost`, which is how the tests drive it
    main()
