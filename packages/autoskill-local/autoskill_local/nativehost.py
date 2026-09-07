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


# Read-only for now, deliberately. The operations that write land once this round trip is proven on a
# real machine, and each one arrives with the person able to see what it will do first.
OPS: dict[str, Callable[[dict[str, Any], Callable[[str], None]], dict[str, Any]]] = {
    "hello": op_hello,
    "state": op_state,
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
