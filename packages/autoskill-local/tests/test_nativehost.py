"""The browser's way in, and the two rules that keep it from being a way in for anything else.

A native messaging host is a hole straight through the browser sandbox: it runs as the person, on
their machine, and does what it is asked. So the framing has to be exact — a length-prefixed protocol
that mis-frames one message desynchronises every message after it — and the caller has to be checked.
"""

from __future__ import annotations

import io
import os
import struct
from typing import ClassVar

import pytest

from autoskill_local import nativehost as nh

ID = "abcdefghijklmnopqrstuvwxyzabcdef"
ORIGIN = f"chrome-extension://{ID}/"


@pytest.fixture(autouse=True)
def only_our_extension(monkeypatch):
    monkeypatch.setenv("AUTOSKILL_ALLOWED_EXTENSIONS", ID)


def framed(*messages: dict) -> io.BytesIO:
    return io.BytesIO(b"".join(nh.encode(m) for m in messages))


def replies(out: io.BytesIO) -> list[dict]:
    out.seek(0)
    return list(nh.read_messages(out))


# --- framing --------------------------------------------------------------------------------------


def test_two_messages_in_one_buffer_are_read_as_two():
    """The browser writes into a pipe; message boundaries are the length prefix and nothing else."""
    got = list(nh.read_messages(framed({"op": "hello"}, {"op": "state"})))
    assert [m["op"] for m in got] == ["hello", "state"]


def test_a_truncated_message_ends_the_conversation_instead_of_guessing():
    """Half a message means the pipe closed — the browser quit, or the extension was disabled."""
    whole = nh.encode({"op": "hello", "params": {"padding": "x" * 100}})
    assert list(nh.read_messages(io.BytesIO(whole[:-10]))) == []
    assert list(nh.read_messages(io.BytesIO(b"\x04\x00"))) == [], "not even a full header"


def test_an_oversized_message_is_refused_rather_than_allocated():
    """The length is attacker-controlled before a single byte of body has been read."""
    with pytest.raises(ValueError, match="exceeds"):
        list(nh.read_messages(io.BytesIO(struct.pack("<I", nh.MAX_MESSAGE + 1) + b"{}")))


def test_what_is_written_can_be_read_back():
    payload = {"id": 1, "kind": "result", "result": {"unicode": "già — ok"}}
    assert list(nh.read_messages(io.BytesIO(nh.encode(payload)))) == [payload]


# --- who may call ----------------------------------------------------------------------------------


def test_only_the_extension_we_shipped_may_drive_this_machine():
    assert nh.origin_allowed(ORIGIN)
    assert nh.origin_allowed(f"chrome-extension://{ID}"), "with or without the trailing slash"
    assert not nh.origin_allowed("chrome-extension://someone-elses-extension-id/")
    assert not nh.origin_allowed("https://example.com/")
    assert not nh.origin_allowed(None)


def test_with_no_allow_list_nobody_is_let_in(monkeypatch):
    """An empty list must mean nobody, never everybody: that is how a hole is left open by accident."""
    monkeypatch.delenv("AUTOSKILL_ALLOWED_EXTENSIONS", raising=False)
    monkeypatch.setattr(nh, "EXTENSION_IDS", ())
    assert not nh.origin_allowed(ORIGIN)


def test_a_refused_caller_gets_an_error_and_nothing_runs(monkeypatch):
    ran: list[str] = []
    monkeypatch.setitem(nh.OPS, "hello", lambda p, s: ran.append("hello") or {})
    out = io.BytesIO()

    code = nh.serve(framed({"id": 1, "op": "hello"}), out, "chrome-extension://not-ours/")

    assert code == 1 and ran == [], "refused before any operation, not after"
    assert replies(out)[0]["code"] == "origin_not_allowed"


# --- dispatch ---------------------------------------------------------------------------------------


def test_hello_says_what_is_on_the_other_end():
    out = io.BytesIO()
    assert nh.serve(framed({"id": 7, "op": "hello"}), out, ORIGIN) == 0
    (reply,) = replies(out)
    assert reply["id"] == 7 and reply["kind"] == "result"
    assert reply["result"]["protocol"] == nh.PROTOCOL and reply["result"]["cli_version"]
    assert "state" in reply["result"]["ops"]


def test_the_machine_state_comes_back_as_data(monkeypatch):
    monkeypatch.setattr("autoskill_local.cli.machine_state", lambda cfg=None: {"agents": [], "logged_in": False})
    out = io.BytesIO()
    nh.serve(framed({"id": 1, "op": "state"}), out, ORIGIN)
    assert replies(out)[0]["result"] == {"agents": [], "logged_in": False}


def test_an_unknown_operation_is_named_and_the_surface_listed():
    out = io.BytesIO()
    nh.serve(framed({"id": 2, "op": "rm -rf /"}), out, ORIGIN)
    (reply,) = replies(out)
    assert reply["kind"] == "error" and reply["code"] == "unknown_op"
    assert "hello" in reply["ops"], "a closed set, and it says what is in it"


def test_progress_arrives_before_the_result_and_carries_the_request_id(monkeypatch):
    def chatty(_params, say):
        say("first")
        say("second")
        return {"done": True}

    monkeypatch.setitem(nh.OPS, "chatty", chatty)
    out = io.BytesIO()
    nh.serve(framed({"id": 9, "op": "chatty"}), out, ORIGIN)

    kinds = [(m["kind"], m.get("message")) for m in replies(out)]
    assert kinds == [("progress", "first"), ("progress", "second"), ("result", None)]
    assert all(m["id"] == 9 for m in replies(out)), "so a page can match answers to what it asked"


def test_a_failing_operation_ends_that_request_and_not_the_conversation(monkeypatch):
    class Named(Exception):
        code = "checksum_mismatch"
        details: ClassVar[dict] = {"url": "http://x"}

    def boom(_params, _say):
        raise Named("refusing to install")

    monkeypatch.setitem(nh.OPS, "boom", boom)
    out = io.BytesIO()
    nh.serve(framed({"id": 1, "op": "boom"}, {"id": 2, "op": "hello"}), out, ORIGIN)

    first, second = replies(out)
    assert first["kind"] == "error" and first["code"] == "checksum_mismatch"
    assert first["details"] == {"url": "http://x"} and "refusing" in first["message"]
    assert second["id"] == 2 and second["kind"] == "result", "the next request still ran"


def test_every_declared_operation_can_actually_be_called():
    """A name in OPS that dispatch cannot reach is worse than an absent one: the page believes it."""
    for name, fn in nh.OPS.items():
        assert callable(fn), name
        assert name in nh.op_hello({}, lambda _: None)["ops"]


def test_the_real_process_speaks_the_protocol_on_its_own_streams(monkeypatch):
    """The in-memory tests cover the logic; this covers the wiring — argv, and binary streams.

    Text-mode streams would translate newlines inside a length-prefixed body on Windows and corrupt
    every message containing one, which no amount of testing `serve()` with a BytesIO would reveal.
    """
    import subprocess
    import sys
    from pathlib import Path

    env = {**os.environ, "AUTOSKILL_ALLOWED_EXTENSIONS": ID, "PYTHONPATH": str(Path(nh.__file__).parents[2])}
    proc = subprocess.run(
        [sys.executable, "-m", "autoskill_local.nativehost", ORIGIN],
        input=nh.encode({"id": 1, "op": "hello"}),
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode()
    (reply,) = list(nh.read_messages(io.BytesIO(proc.stdout)))
    assert reply["id"] == 1 and reply["result"]["protocol"] == nh.PROTOCOL

    refused = subprocess.run(
        [sys.executable, "-m", "autoskill_local.nativehost", "chrome-extension://not-ours/"],
        input=nh.encode({"id": 1, "op": "state"}),
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert refused.returncode == 1
    assert next(iter(nh.read_messages(io.BytesIO(refused.stdout))))["code"] == "origin_not_allowed"


def test_the_shipped_id_is_the_one_the_manifest_actually_produces():
    """Three places have to name the same extension, and two of them cannot check each other.

    Chrome derives an extension's id from the public key pinned in its manifest. The allow-list here
    and the id the server puts in its setup script are both written by hand against that derivation —
    so a changed key silently leaves a host that refuses the extension it was installed for, and a
    setup that looks complete. This is the one place the three can be compared.
    """
    import base64
    import hashlib
    import json
    from pathlib import Path

    manifest_path = Path(nh.__file__).parents[3] / "extension" / "manifest.json"
    if not manifest_path.is_file():  # the wheel ships without the extension beside it
        pytest.skip("extension/ is not in this tree")
    key = json.loads(manifest_path.read_text(encoding="utf-8")).get("key")
    assert key, "without a pinned key the id changes on every machine and no allow-list can be written"

    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    derived = "".join(chr(ord("a") + int(c, 16)) for c in digest)
    assert derived in nh.EXTENSION_IDS, f"the manifest produces {derived}, which this host does not allow"
