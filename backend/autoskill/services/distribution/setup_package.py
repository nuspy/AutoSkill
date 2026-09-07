"""The one thing a person still has to run by hand, made as small as it can be.

Every act that touches somebody's machine is a command they have to type, and the browser extension
exists to end that — but the extension itself cannot install itself, and the native messaging host it
needs cannot be registered from inside a browser. So one manual step survives, and this is it: a
script the application hands over, already knowing its own address and the id of the extension it
ships, so that nothing has to be filled in by the reader.

The script is generated rather than stored because half of it is facts only this server has: where it
lives, which wheel it publishes, which extension it is pairing with. A stored script would have blanks
in exactly those places, and a blank is a thing to get wrong.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[4] / "extension"

# What is genuinely undoable from a browser, in order. Everything after this is the extension's job.
#
# A raw string, because it is full of Windows backslash paths — but that means the `\` line-
# continuation that once opened it (`r"""\`) is now a literal backslash, and the served script began
# with a stray `\` that PowerShell tried to run as a command. So the first line opens the content
# directly, with nothing before it.
_WINDOWS = r"""# AutoSkill setup — installs the command line tool and lets your browser talk to it.
# Nothing here needs administrator rights: it all writes under your own user.
$ErrorActionPreference = "Stop"

# `$ErrorActionPreference` does not cover an external program: PowerShell ignores its exit code, so
# a step that failed would scroll past and the script would go on announcing success. Every command
# below is a program, and the whole point of this script is that the person can trust it.
function Step($what, [scriptblock]$do) {{
  Write-Host $what
  & $do
  if ($LASTEXITCODE -ne 0) {{
    Write-Host ""
    Write-Host "That step failed (exit $LASTEXITCODE). Nothing after it has run." -ForegroundColor Red
    exit 1
  }}
}}

Write-Host "1/4  Installing the AutoSkill command line tool"
if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {{
  python -m pip install --user pipx
  python -m pipx ensurepath
}}
Step "" {{ pipx install --force "{wheel_url}" }}

# `pipx` puts the command in a directory the running shell may not know about yet.
$env:PATH = "$HOME\.local\bin;$env:PATH"

Step "2/4  Connecting this machine to {server_url}" {{ autoskill login "{server_url}" }}
Step "3/4  Letting your browser reach it" {{ autoskill browser install --extension-id "{extension_id}" }}

Write-Host "4/4  Unpacking the browser extension"
$dir = Join-Path $HOME ".autoskill\\extension"
Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Invoke-WebRequest -Uri "{extension_url}" -OutFile "$env:TEMP\\autoskill-extension.zip"
Expand-Archive -Path "$env:TEMP\\autoskill-extension.zip" -DestinationPath $dir -Force

Write-Host ""
Write-Host "Done. One step left, and only the browser can do it:" -ForegroundColor Green
Write-Host "  1. open its extensions page  (chrome://extensions, edge://extensions, brave://extensions, ...)"
Write-Host "  2. turn ON 'Developer mode'  -- without it there is no 'Load unpacked' button" -ForegroundColor Yellow
Write-Host "  3. 'Load unpacked', and choose:  $dir"
Write-Host ""
Write-Host "Do this in each browser you set up above. Chrome has not allowed an extension to be"
Write-Host "installed from a local file since version 33, so this last click is yours."
"""

_UNIX = """\
#!/bin/sh
# AutoSkill setup — installs the command line tool and lets your browser talk to it.
# Nothing here needs root: it all writes under your own user.
set -e

echo "1/4  Installing the AutoSkill command line tool"
command -v pipx >/dev/null 2>&1 || python3 -m pip install --user pipx
pipx install --force "{wheel_url}"

# `pipx` puts the command in a directory the running shell may not know about yet.
PATH="$HOME/.local/bin:$PATH"; export PATH

echo "2/4  Connecting this machine to {server_url}"
autoskill login "{server_url}"

echo "3/4  Letting your browser reach it"
autoskill browser install --extension-id "{extension_id}"

echo "4/4  Unpacking the browser extension"
dir="$HOME/.autoskill/extension"
rm -rf "$dir" && mkdir -p "$dir"
tmp=$(mktemp -d)
curl -fsSL "{extension_url}" -o "$tmp/extension.zip"
unzip -oq "$tmp/extension.zip" -d "$dir"

echo
echo "Done. One step left, and only the browser can do it:"
echo "  1. open its extensions page  (chrome://extensions, brave://extensions, ...)"
echo "  2. turn ON 'Developer mode'  -- without it there is no 'Load unpacked' button"
echo "  3. 'Load unpacked', and choose:  $dir"
echo
echo "Do this in each browser you set up above. Chrome has not allowed an extension to be"
echo "installed from a local file since version 33, so this last click is yours."
"""

# A double-clickable wrapper for the person who would rather not paste a command. It exists to be run
# from a browser download, which is exactly the case Windows now guards hardest: Smart App Control
# blocks a downloaded .bat outright on updated machines, with no override. So the paste-one-line
# command is offered first and this second, with the caveat said out loud — a fallback, not the path.
_WINDOWS_BAT = """\
@echo off
REM AutoSkill setup. Runs the PowerShell setup with the current user's rights -- no administrator.
REM If Windows blocks this file, use the copy-and-paste command on the AutoSkill page instead.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm '{server_url}/dl/installer/windows' | iex"
echo.
pause
"""

PLATFORMS = {"windows": ("autoskill-setup.ps1", _WINDOWS), "unix": ("autoskill-setup.sh", _UNIX)}


def setup_script(platform: str, *, server_url: str, wheel_url: str, extension_id: str) -> tuple[str, str]:
    """(filename, contents) of the setup script for a platform, with nothing left to fill in."""
    filename, template = PLATFORMS[platform]
    return filename, template.format(
        server_url=server_url.rstrip("/"),
        wheel_url=wheel_url,
        extension_id=extension_id,
        extension_url=f"{server_url.rstrip('/')}/dl/extension.zip",
    )


def setup_bat(server_url: str) -> tuple[str, str]:
    """A .bat that runs the Windows setup — for a double-click, when a pasted command is not wanted."""
    return "autoskill-setup.bat", _WINDOWS_BAT.format(server_url=server_url.rstrip("/"))


def paste_command(platform: str, server_url: str) -> str:
    """The one line to paste into a shell — the way that dodges Mark-of-the-Web entirely.

    The script arrives as text through the shell, never as a downloaded file, so there is nothing for
    SmartScreen or Smart App Control to flag. It is how command-line tools are installed today.
    """
    base = server_url.rstrip("/")
    if platform == "windows":
        return f"irm {base}/dl/installer/windows | iex"
    return f"curl -fsSL {base}/dl/installer/unix | sh"


def extension_zip() -> bytes:
    """The extension, zipped from the repository.

    Deterministic — sorted entries, a fixed timestamp — so that downloading it twice gives the same
    bytes. A person comparing two downloads should not find a difference that is only the clock.
    """
    if not EXTENSION_DIR.is_dir():
        raise FileNotFoundError(EXTENSION_DIR)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in EXTENSION_DIR.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(str(path.relative_to(EXTENSION_DIR)).replace("\\", "/"), (2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()
