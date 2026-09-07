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
_WINDOWS = """\
# AutoSkill setup — installs the command line tool and lets your browser talk to it.
# Nothing here needs administrator rights: it all writes under your own user.
$ErrorActionPreference = "Stop"

Write-Host "1/4  Installing the AutoSkill command line tool"
if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {{
  python -m pip install --user pipx
  python -m pipx ensurepath
}}
pipx install --force "{wheel_url}"

Write-Host "2/4  Connecting this machine to {server_url}"
autoskill login "{server_url}"

Write-Host "3/4  Letting your browser reach it"
autoskill browser install --extension-id "{extension_id}"

Write-Host "4/4  Unpacking the browser extension"
$dir = Join-Path $HOME ".autoskill\\extension"
Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Invoke-WebRequest -Uri "{extension_url}" -OutFile "$env:TEMP\\autoskill-extension.zip"
Expand-Archive -Path "$env:TEMP\\autoskill-extension.zip" -DestinationPath $dir -Force

Write-Host ""
Write-Host "Done. One step left, and only Chrome can do it:" -ForegroundColor Green
Write-Host "  1. open  chrome://extensions"
Write-Host "  2. turn on 'Developer mode'"
Write-Host "  3. 'Load unpacked', and choose:  $dir"
Write-Host ""
Write-Host "Chrome has not allowed an extension to be installed from a local file since version 33,"
Write-Host "so this last click is yours. Everything after it happens in the AutoSkill page."
"""

_UNIX = """\
#!/bin/sh
# AutoSkill setup — installs the command line tool and lets your browser talk to it.
# Nothing here needs root: it all writes under your own user.
set -e

echo "1/4  Installing the AutoSkill command line tool"
command -v pipx >/dev/null 2>&1 || python3 -m pip install --user pipx
pipx install --force "{wheel_url}"

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
echo "  1. open  chrome://extensions"
echo "  2. turn on 'Developer mode'"
echo "  3. 'Load unpacked', and choose:  $dir"
echo
echo "Chrome has not allowed an extension to be installed from a local file since version 33,"
echo "so this last click is yours. Everything after it happens in the AutoSkill page."
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
