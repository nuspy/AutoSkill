"""Registering the native messaging host with the browsers on this machine.

The browser will not launch a host it has not been told about, and where it looks differs by platform
and by browser: a registry key under HKCU on Windows, a JSON file in a per-browser directory on macOS
and Linux. All of them point at the same small manifest naming the executable and — the part that
matters — the extensions permitted to talk to it.

Everything here writes under the current user. Registering a native messaging host needs no
administrator, which is why this is the half of the bootstrap that can be automated; installing the
extension itself is the half that cannot.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

HOST_NAME = "com.autoskill.host"
EXECUTABLE = "autoskill-native-host"

# Every Chromium-family browser we know how to register with, in one table so nothing drifts:
#   name      — for the person, in the chooser
#   win_key   — the HKCU key it reads native-messaging manifests from, or None if it reads Chrome's
#   darwin    — the per-user manifest directory on macOS
#   linux     — the same on Linux
#   markers   — a profile directory whose existence means this browser is actually used here, under
#               LOCALAPPDATA on Windows, $HOME on POSIX. Detection is by profile, not by executable:
#               a browser present but never opened has no host to register into anyway.
BROWSERS: dict[str, dict[str, str | None]] = {
    "chrome": {
        "name": "Google Chrome",
        "win_key": r"Software\Google\Chrome\NativeMessagingHosts",
        "darwin": "Library/Application Support/Google/Chrome/NativeMessagingHosts",
        "linux": ".config/google-chrome/NativeMessagingHosts",
        "win_marker": r"Google\Chrome\User Data",
        "posix_marker": ".config/google-chrome",
        "darwin_marker": "Library/Application Support/Google/Chrome",
    },
    "edge": {
        "name": "Microsoft Edge",
        "win_key": r"Software\Microsoft\Edge\NativeMessagingHosts",
        "darwin": "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
        "linux": ".config/microsoft-edge/NativeMessagingHosts",
        "win_marker": r"Microsoft\Edge\User Data",
        "posix_marker": ".config/microsoft-edge",
        "darwin_marker": "Library/Application Support/Microsoft Edge",
    },
    "brave": {
        "name": "Brave",
        "win_key": r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
        "darwin": "Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts",
        "linux": ".config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
        "win_marker": r"BraveSoftware\Brave-Browser\User Data",
        "posix_marker": ".config/BraveSoftware/Brave-Browser",
        "darwin_marker": "Library/Application Support/BraveSoftware/Brave-Browser",
    },
    "vivaldi": {
        "name": "Vivaldi",
        "win_key": r"Software\Vivaldi\NativeMessagingHosts",
        "darwin": "Library/Application Support/Vivaldi/NativeMessagingHosts",
        "linux": ".config/vivaldi/NativeMessagingHosts",
        "win_marker": r"Vivaldi\User Data",
        "posix_marker": ".config/vivaldi",
        "darwin_marker": "Library/Application Support/Vivaldi",
    },
    "opera": {
        # Opera reads Chrome's key on Windows, so `win_key` is None and registration falls back to it.
        "name": "Opera",
        "win_key": None,
        "darwin": "Library/Application Support/com.operasoftware.Opera/NativeMessagingHosts",
        "linux": ".config/opera/NativeMessagingHosts",
        "win_marker": "Opera Software",
        "posix_marker": ".config/opera",
        "darwin_marker": "Library/Application Support/com.operasoftware.Opera",
    },
    "chromium": {
        "name": "Chromium",
        "win_key": r"Software\Chromium\NativeMessagingHosts",
        "darwin": "Library/Application Support/Chromium/NativeMessagingHosts",
        "linux": ".config/chromium/NativeMessagingHosts",
        "win_marker": r"Chromium\User Data",
        "posix_marker": ".config/chromium",
        "darwin_marker": "Library/Application Support/Chromium",
    },
}


def installed_browsers(home: Path | None = None) -> list[str]:
    """Which of the known browsers actually have a profile on this machine, best-known first.

    The person may have several, or one, or a fork we do not list; the setup asks rather than assumes.
    Detection is by the profile directory, because that is what says a browser is used here — an
    executable present but never opened has no user-level place to register a host into.
    """
    home = home or Path.home()
    base = Path(os.environ["LOCALAPPDATA"]) if sys.platform == "win32" and "LOCALAPPDATA" in os.environ else home
    marker = "win_marker" if sys.platform == "win32" else ("darwin_marker" if sys.platform == "darwin" else "posix_marker")
    found = []
    for bid, meta in BROWSERS.items():
        rel = meta.get(marker)
        if rel and (base / rel).exists():
            found.append(bid)
    return found


def _win_key(browser: str) -> str | None:
    """The HKCU key a browser reads, mapping the ones that read Chrome's onto Chrome's."""
    meta = BROWSERS.get(browser)
    if meta is None:
        return None
    return meta["win_key"] or BROWSERS["chrome"]["win_key"]  # Opera and other forks fall back to Chrome's


def host_executable(shim_dir: Path | None = None) -> str:
    """An absolute path to something the browser can launch, writing a shim when there is no script.

    `path` in a native messaging manifest is an executable, not a command line: the browser starts it
    directly, with no shell to split arguments and no PATH of its own. So `python -m autoskill_local
    .nativehost` cannot go there — it has to become a file. `pipx` installs the console script and
    there is nothing to do; a source checkout has the module and not the script, and gets a one-line
    launcher instead.
    """
    found = shutil.which(EXECUTABLE)
    if found:
        return found
    directory = shim_dir or (Path.home() / ".autoskill")
    directory.mkdir(parents=True, exist_ok=True)
    # `newline=""` because text mode translates every "\n" into the platform ending, which turned the
    # "\r\n" a batch file wants into "\r\r\n".
    if sys.platform == "win32":
        shim = directory / "autoskill-native-host.bat"
        body = f'@echo off\r\n"{sys.executable}" -m autoskill_local.nativehost %*\r\n'
    else:
        shim = directory / "autoskill-native-host.sh"
        body = f'#!/bin/sh\nexec "{sys.executable}" -m autoskill_local.nativehost "$@"\n'
    shim.write_text(body, encoding="utf-8", newline="")
    if sys.platform != "win32":
        shim.chmod(0o755)
    return str(shim)


def manifest(extension_ids: list[str], executable: str | None = None, shim_dir: Path | None = None) -> dict:
    return {
        "name": HOST_NAME,
        "description": "AutoSkill: installs skills and trials on this machine",
        "path": executable or host_executable(shim_dir),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{i}/" for i in extension_ids],
    }


def manifest_dir(browser: str, home: Path | None = None) -> Path | None:
    home = home or Path.home()
    meta = BROWSERS.get(browser)
    if meta is None:
        return None
    rel = meta.get("darwin" if sys.platform == "darwin" else "linux")
    return home / rel if rel else None


def install(extension_ids: list[str], *, home: Path | None = None, browsers: list[str] | None = None) -> list[str]:
    """Write the host manifest wherever the chosen browsers will look. Returns what it wrote.

    `browsers` defaults to the ones actually installed here, not to every one we know: a machine has
    Chrome but not Vivaldi far more often than it has both, and a host registered for a browser that
    is not there is dead weight. A browser in the list but missing a place to write is skipped rather
    than raised — refusing to register anywhere because one is absent would be a strange way to fail.
    """
    written: list[str] = []
    wanted = browsers if browsers is not None else installed_browsers(home)
    doc = json.dumps(manifest(extension_ids, shim_dir=(home / ".autoskill") if home else None), indent=2) + "\n"
    if sys.platform == "win32" and home is None:
        return _install_windows(doc, wanted)
    for browser in wanted:
        directory = manifest_dir(browser, home)
        if directory is None:
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{HOST_NAME}.json"
            path.write_text(doc, encoding="utf-8")
            written.append(str(path))
        except OSError:
            continue
    return written


def _install_windows(doc: str, browsers: list[str]) -> list[str]:
    """On Windows the manifest is a file, and the registry value points at it.

    The key lives under HKCU, so this needs no administrator — which is the whole reason the browser
    half of the bootstrap can be done by an installer the person simply runs.
    """
    import winreg

    written: list[str] = []
    target = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AutoSkill"
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{HOST_NAME}.json"
    path.write_text(doc, encoding="utf-8")
    seen: set[str] = set()
    for browser in browsers:
        key = _win_key(browser)
        # Opera and other forks map onto Chrome's key; writing it twice is the same value, so skip.
        if key is None or key in seen:
            continue
        seen.add(key)
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}") as handle:
                winreg.SetValueEx(handle, None, 0, winreg.REG_SZ, str(path))
            written.append(f"HKCU\\{key}\\{HOST_NAME}")
        except OSError:
            continue
    return written
