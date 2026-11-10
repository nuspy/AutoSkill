"""Registering the native messaging host, which is the half of the bootstrap that can be automated.

The browser will not launch a host it has not been told about, and the manifest it reads names both
the executable and — the part that matters — who is allowed to talk to it.
"""

from __future__ import annotations

import json
from pathlib import Path

from autoskill_local import browserhost as bh

ID = "abcdefghijklmnopqrstuvwxyzabcdef"


def test_the_manifest_names_the_host_and_who_may_call_it():
    m = bh.manifest([ID], executable="/usr/bin/autoskill-native-host")
    assert m["name"] == bh.HOST_NAME and m["type"] == "stdio"
    assert m["path"] == "/usr/bin/autoskill-native-host"
    assert m["allowed_origins"] == [f"chrome-extension://{ID}/"]


def test_it_writes_where_each_browser_looks(tmp_path: Path, monkeypatch):
    """One file per browser, all pointing at the same host. Chrome without Opera is the normal case."""
    monkeypatch.setattr(bh.sys, "platform", "linux")
    written = bh.install([ID], home=tmp_path, browsers=["chrome", "opera"])

    assert len(written) == 2
    doc = json.loads((tmp_path / ".config/google-chrome/NativeMessagingHosts" / f"{bh.HOST_NAME}.json").read_text())
    assert doc["allowed_origins"] == [f"chrome-extension://{ID}/"]
    assert (tmp_path / ".config/opera/NativeMessagingHosts" / f"{bh.HOST_NAME}.json").exists()


def test_a_browser_that_is_not_there_is_skipped_not_fatal(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bh.sys, "platform", "linux")
    assert bh.install([ID], home=tmp_path, browsers=["chrome", "nonesuch"]) == [
        str(tmp_path / ".config/google-chrome/NativeMessagingHosts" / f"{bh.HOST_NAME}.json")
    ]


def test_the_path_is_absolute_because_the_browser_has_no_shell():
    """The browser launches the host directly: no PATH lookup, no shell, no working directory."""
    path = bh.manifest([ID])["path"]
    assert path and (Path(path.split(" ")[0]).is_absolute() or Path(path).is_absolute())


def test_registering_with_nobody_allowed_would_be_a_host_nothing_can_reach():
    """Refusing this is the point: a host registered with an empty allow-list is dead weight, and an
    allow-list that means "anyone" is the way this becomes a hole. The CLI stops before calling here."""
    assert bh.manifest([])["allowed_origins"] == []


def test_a_source_checkout_gets_a_launcher_the_browser_can_actually_start(tmp_path: Path, monkeypatch):
    """`path` is an executable, not a command line: the browser starts it with no shell to split it.

    So `python -m autoskill_local.nativehost` cannot go there. Without this the manifest would look
    right, register fine, and fail the moment the browser tried to launch it.
    """
    monkeypatch.setattr(bh.shutil, "which", lambda _name: None)  # no console script, as in a checkout
    path = Path(bh.host_executable(shim_dir=tmp_path))

    assert path.is_absolute() and path.exists()
    assert " " not in path.name, "one file, not a command line"
    raw = path.read_bytes()
    assert b"autoskill_local.nativehost" in raw
    if bh.sys.platform == "win32":
        # text mode would translate the "\n" and leave "\r\r\n" in a batch file
        assert b"\r\r\n" not in raw
    else:
        assert path.stat().st_mode & 0o111, "and it has to be runnable"


def test_the_console_script_is_preferred_when_there_is_one(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bh.shutil, "which", lambda _name: "/usr/local/bin/autoskill-native-host")
    assert bh.host_executable(shim_dir=tmp_path) == "/usr/local/bin/autoskill-native-host"
    assert not list(tmp_path.iterdir()), "and nothing is written when nothing is needed"


def test_detection_is_by_profile_because_that_is_what_says_it_is_used(tmp_path: Path, monkeypatch):
    """A browser with a profile is one the person opens; an executable alone has no host to hold."""
    monkeypatch.setattr(bh.sys, "platform", "linux")
    (tmp_path / ".config/google-chrome").mkdir(parents=True)
    (tmp_path / ".config/BraveSoftware/Brave-Browser").mkdir(parents=True)
    found = bh.installed_browsers(home=tmp_path)
    assert set(found) == {"chrome", "brave"}
    assert "edge" not in found, "no Edge profile here, so Edge is not offered"


def test_install_defaults_to_the_browsers_that_are_actually_here(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bh.sys, "platform", "linux")
    (tmp_path / ".config/vivaldi").mkdir(parents=True)
    written = bh.install([ID], home=tmp_path)  # no browsers given
    assert written == [str(tmp_path / ".config/vivaldi/NativeMessagingHosts" / f"{bh.HOST_NAME}.json")]


def test_each_browser_reads_its_own_windows_key():
    """Regression: Opera does NOT read Chrome's HKCU key. Registering the host under Chrome's key left
    Opera unable to find it — its popup failed with "the message port closed before a response was
    received". Every browser here has its own key, spelled for that browser."""
    opera_key = bh._win_key("opera")
    assert opera_key and opera_key != bh.BROWSERS["chrome"]["win_key"], "Opera has its own key, not Chrome's"
    assert "Opera Software" in opera_key
    assert "Opera GX" in (bh._win_key("operagx") or "")
    assert bh._win_key("brave") and "BraveSoftware" in bh._win_key("brave"), "Brave has its own key"


def test_brave_and_vivaldi_are_known_now():
    """They were missing, and a machine with Brave installed got a host registered for browsers it
    does not use while the one it does use was skipped."""
    for bid in ("brave", "vivaldi"):
        assert bid in bh.BROWSERS
        assert bh.BROWSERS[bid]["name"] and bh.BROWSERS[bid]["linux"].endswith("NativeMessagingHosts")
