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

# Where each Chromium browser reads user-level host manifests. The Windows entries are registry keys
# rather than paths, and are handled separately.
POSIX_DIRS: dict[str, dict[str, str]] = {
    "darwin": {
        "chrome": "Library/Application Support/Google/Chrome/NativeMessagingHosts",
        "chromium": "Library/Application Support/Chromium/NativeMessagingHosts",
        "opera": "Library/Application Support/com.operasoftware.Opera/NativeMessagingHosts",
        "edge": "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
    },
    "linux": {
        "chrome": ".config/google-chrome/NativeMessagingHosts",
        "chromium": ".config/chromium/NativeMessagingHosts",
        "opera": ".config/opera/NativeMessagingHosts",
        "edge": ".config/microsoft-edge/NativeMessagingHosts",
    },
}
WINDOWS_KEYS: dict[str, str] = {
    "chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "chromium": r"Software\Chromium\NativeMessagingHosts",
    # Opera reads Chrome's key on Windows rather than one of its own.
    "edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
}


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
    table = POSIX_DIRS.get("darwin" if sys.platform == "darwin" else "linux")
    rel = (table or {}).get(browser)
    return home / rel if rel else None


def install(extension_ids: list[str], *, home: Path | None = None, browsers: list[str] | None = None) -> list[str]:
    """Write the host manifest wherever the browsers on this machine will look. Returns what it wrote.

    Every browser is attempted and failures are skipped rather than raised: a machine has Chrome but
    not Opera far more often than it has both, and refusing to register anywhere because one browser
    is absent would be a strange way to fail.
    """
    written: list[str] = []
    wanted = browsers or ["chrome", "chromium", "opera", "edge"]
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
    for browser in browsers:
        key = WINDOWS_KEYS.get("chrome" if browser == "opera" else browser)
        if key is None:
            continue
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}") as handle:
                winreg.SetValueEx(handle, None, 0, winreg.REG_SZ, str(path))
            written.append(f"HKCU\\{key}\\{HOST_NAME}")
        except OSError:
            continue
    return written
