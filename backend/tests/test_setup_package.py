"""The one manual step, and the two ways it could be handed over broken.

The extension cannot install itself and a native messaging host cannot be registered from inside a
browser, so exactly one step survives. Since it is the only one, it has to arrive complete: a script
with a blank in it is a blank the reader has to fill, which is the thing this whole feature removes.
"""

from __future__ import annotations

import io
import zipfile

from autoskill.services.distribution import setup_package


def test_the_script_arrives_with_nothing_left_to_fill_in():
    for platform in setup_package.PLATFORMS:
        name, body = setup_package.setup_script(
            platform,
            server_url="https://skills.example.com/",
            wheel_url="https://skills.example.com/dl/autoskill-local/autoskill_local-9.9.9-py3-none-any.whl",
            extension_id="abcdefghijklmnopqrstuvwxyzabcdef",
        )
        assert name.startswith("autoskill-setup.")
        assert "{" not in body.replace("{{", "").replace("}}", "") or platform == "windows"
        # the three facts only this server has
        assert "autoskill_local-9.9.9-py3-none-any.whl" in body
        assert "https://skills.example.com/dl/extension.zip" in body
        assert "--extension-id \"abcdefghijklmnopqrstuvwxyzabcdef\"" in body
        # and the trailing slash of the server url is not doubled into the addresses
        assert "https://skills.example.com//" not in body


def test_it_says_plainly_which_step_the_person_still_has_to_do():
    """Chrome has not allowed a local .crx since version 33; pretending otherwise wastes an evening."""
    for platform in setup_package.PLATFORMS:
        _name, body = setup_package.setup_script(
            platform, server_url="https://x", wheel_url="https://x/w.whl", extension_id="abc"
        )
        assert "chrome://extensions" in body and "Developer mode" in body
        assert "version 33" in body, "and why, so it does not read as a defect"


def test_nothing_in_the_script_needs_administrator():
    for platform in setup_package.PLATFORMS:
        _name, body = setup_package.setup_script(
            platform, server_url="https://x", wheel_url="https://x/w.whl", extension_id="abc"
        )
        lowered = body.lower()
        assert "runas" not in lowered and "sudo " not in lowered
        assert "--user" in body or "pipx" in body


def test_the_extension_is_zipped_whole_and_the_same_every_time():
    once, twice = setup_package.extension_zip(), setup_package.extension_zip()
    assert once == twice, "two downloads that differ only by the clock are two things to compare"
    names = set(zipfile.ZipFile(io.BytesIO(once)).namelist())
    assert {"manifest.json", "background.js", "content.js"} <= names
    manifest = zipfile.ZipFile(io.BytesIO(once)).read("manifest.json").decode()
    assert '"nativeMessaging"' in manifest, "without it the extension cannot reach the host at all"


# --- the routes that hand it over -----------------------------------------------------------------


async def test_the_installer_is_refused_rather_than_handed_over_incomplete(app_client, monkeypatch):
    """Without an extension id the script would register a host nothing is allowed to call.

    That setup looks like it worked. The person finds out later, from the one part of this feature
    whose whole purpose is to remove doubt — so it is refused at the download, with the setting named.
    """
    from autoskill.config import get_settings

    monkeypatch.setattr(get_settings(), "extension_id", "", raising=False)
    res = await app_client.get("/dl/installer/windows")
    assert res.status_code == 404
    body = res.json()["error"]
    assert body["code"] in ("extension_id_not_set", "wheel_not_found")
    if body["code"] == "extension_id_not_set":
        assert "AUTOSKILL_EXTENSION_ID" in body["message"], "and it says which setting"


async def test_an_unknown_platform_says_which_ones_exist(app_client):
    res = await app_client.get("/dl/installer/amiga")
    assert res.status_code == 404
    assert res.json()["error"]["details"]["platforms"] == ["unix", "windows"]


async def test_the_extension_can_be_fetched_without_logging_in(app_client):
    """It is a public artefact like the wheel: nothing in it is secret, and the setup script — which
    runs before anyone has credentials on this machine — has to be able to download it."""
    res = await app_client.get("/dl/extension.zip")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert b"manifest.json" in res.content


def test_the_id_this_server_hands_out_is_the_extension_it_ships():
    """The setup script registers a host that accepts one id; the extension it unpacks has another
    only if somebody changed one and not the other. Then the host refuses the extension it was
    installed for, and nothing in the setup says so — it simply does not work."""
    import base64
    import hashlib
    import json

    from autoskill.config import get_settings

    manifest_path = setup_package.EXTENSION_DIR / "manifest.json"
    key = json.loads(manifest_path.read_text(encoding="utf-8"))["key"]
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    derived = "".join(chr(ord("a") + int(c, 16)) for c in digest)
    assert get_settings().extension_id == derived, "the default must name the extension this server serves"


def test_a_step_that_fails_stops_the_script_instead_of_scrolling_past():
    """`$ErrorActionPreference` does not cover an external program, and every step here is one.

    Found the hard way: the CLI on the machine was an old build with no `browser` command, that step
    failed, and the script went on to print "Done" and a list of things it had not done.
    """
    _name, body = setup_package.setup_script("windows", server_url="http://x", wheel_url="http://x/w.whl", extension_id="abc")
    assert "$LASTEXITCODE -ne 0" in body, "an exit code has to be looked at for it to mean anything"
    assert "Nothing after it has run" in body
    for command in ("autoskill login", "autoskill browser install"):
        assert "Step " in body and command in body
        # each one inside a Step block, not bare
        line = next(line for line in body.splitlines() if command in line)
        assert line.strip().startswith("Step "), f"{command} is not guarded"


def test_the_windows_script_carries_real_paths():
    r"""A template full of Windows paths lived in a non-raw string, so `\b` had already silently
    become a backspace and `$HOME\.local\bin` named a directory that does not exist."""
    _name, body = setup_package.setup_script(
        "windows", server_url="http://x", wheel_url="http://x/w.whl", extension_id="abc"
    )
    assert not any(c in body for c in "\b\f\v"), "no escape has been interpreted on its way here"
    path_line = next(line for line in body.splitlines() if "$env:PATH" in line)
    assert ".local" in path_line and "bin" in path_line and "localin" not in path_line
    assert "extension" in next(line for line in body.splitlines() if "$dir = " in line)


def test_the_paste_command_dodges_mark_of_the_web():
    """The recommended way is a line pasted into a shell, not a downloaded file.

    Smart App Control blocks a downloaded .bat outright on updated Windows machines, with no override.
    A command reaches the shell as text — nothing for SmartScreen to flag — which is how command-line
    tools are installed today.
    """
    assert setup_package.paste_command("windows", "https://x/") == "irm https://x/dl/installer/windows | iex"
    assert setup_package.paste_command("unix", "https://x") == "curl -fsSL https://x/dl/installer/unix | sh"


def test_the_bat_runs_the_paste_command_rather_than_carrying_the_script():
    """So the .bat itself stays tiny and the logic lives in one place, the served script."""
    name, body = setup_package.setup_bat("https://x/")
    assert name == "autoskill-setup.bat"
    assert "irm 'https://x/dl/installer/windows' | iex" in body
    assert "no administrator" in body.lower()


async def test_the_bat_route_is_served_and_wins_over_the_platform_route(app_client):
    res = await app_client.get("/dl/installer/windows.bat")
    assert res.status_code == 200
    assert res.headers["content-disposition"].endswith('autoskill-setup.bat"')
    assert b"| iex" in res.content, "not the PowerShell script served as a platform"


def test_the_script_starts_with_something_a_shell_can_run():
    r"""A generation test asserted the strings inside; none checked the very first character.

    A raw-string opening left a literal `\` at the top, and PowerShell tried to run it as a command:
    `The term '\' is not recognized`. The first thing on the first line has to be a comment or code,
    never a stray escape.
    """
    for platform in setup_package.PLATFORMS:
        _name, body = setup_package.setup_script(
            platform, server_url="http://x", wheel_url="http://x/w.whl", extension_id="abc"
        )
        first = body.splitlines()[0]
        assert not body.startswith(("\\", "\n", "\r")), f"{platform} script starts with {body[0]!r}"
        assert first.startswith("#"), f"{platform} first line is {first!r}, not a comment"
