from pathlib import Path

import pytest

from autoskill_local.targets import detect_targets, get_target
from autoskill_local.targets.base import McpRegistration


@pytest.mark.parametrize("target_id", ["hermes", "openclaw", "claude_code", "codex", "antigravity"])
def test_install_register_and_clean_removal(tmp_path: Path, target_id: str):
    pkg = tmp_path / "pkg" / "invoice-check"
    pkg.mkdir(parents=True)
    (pkg / "SKILL.md").write_text("---\nname: invoice-check\ndescription: d\n---\nbody\n")
    home = tmp_path / "home"
    target = get_target(target_id, home=home)
    assert not target.detect()

    # pre-existing skill folder is backed up and restored on removal
    existing = target.skill_dir / "invoice-check"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("old")
    manifest = target.install_skill(pkg, "invoice-check")
    assert (target.skill_dir / "invoice-check" / "SKILL.md").read_text().startswith("---")
    assert manifest["backup_dir"] and Path(manifest["backup_dir"]).exists()
    assert target.detect() and target_id in detect_targets(home=home)

    reg = target.register_mcp(
        McpRegistration(name="autoskill-companion", command="autoskill-companion", env={"AUTOSKILL_URL": "http://x"})
    )
    assert Path(reg["config"]).exists()
    servers = target.registered_mcps()
    assert "autoskill-companion" in servers
    entry = servers["autoskill-companion"]
    assert entry.get("command") == "autoskill-companion" and entry.get("env", {}).get("AUTOSKILL_URL") == "http://x"
    if target_id in ("hermes", "claude_code"):
        assert entry["type"] == "stdio"
    # re-registering is idempotent and keeps other servers
    target.register_mcp(McpRegistration(name="other", url="http://localhost:3000"))
    target.register_mcp(McpRegistration(name="autoskill-companion", command="autoskill-companion"))
    servers = target.registered_mcps()
    assert set(servers) == {"autoskill-companion", "other"} and "env" not in servers["autoskill-companion"]

    target.unregister_mcp("autoskill-companion")
    assert set(target.registered_mcps()) == {"other"}
    target.remove_skill("invoice-check", manifest)
    assert (target.skill_dir / "invoice-check" / "SKILL.md").read_text() == "old"


def test_unknown_target():
    with pytest.raises(KeyError):
        get_target("emacs")


# --- finding the agent before installing into it ---------------------------------------------
#
# Every one of these is a bug that actually happened. Hermes was assumed to live in `~/.hermes`
# while it was under `AppData/Local/hermes`: detection never saw it, the dashboard offered a target
# list without the very agent in use, and installing "for Hermes" created `~/.hermes` and put the
# skill there — a directory Hermes has never once read, with every step reporting success.


def test_the_agents_own_variable_says_where_it_lives(tmp_path: Path, monkeypatch):
    elsewhere = tmp_path / "opt" / "hermes"
    elsewhere.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(elsewhere))
    t = get_target("hermes")
    assert t.base == elsewhere and t.detect() and t.base_source == "$HERMES_HOME"
    assert t.skill_dir == elsewhere / "skills"


def test_an_explicit_home_outranks_the_environment(tmp_path: Path, monkeypatch):
    """A caller that named a home must reach that home and nothing else.

    This is the rule that keeps a test suite out of somebody's live installation, and it was learnt
    the hard way: with `HERMES_HOME` set, tests running against a temporary directory installed a
    fixture skill into the real agent and rewrote its configuration.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "real"))
    (tmp_path / "real").mkdir()
    t = get_target("hermes", home=tmp_path / "sandbox")
    assert t.base == tmp_path / "sandbox" / "AppData/Local/hermes"
    assert not t.detect() and t.base_source == "assumed"


def test_the_person_can_declare_where_an_agent_is(tmp_path: Path):
    where = tmp_path / "D" / "tools" / "hermes"
    where.mkdir(parents=True)
    t = get_target("hermes", home_dir=where)
    assert t.base == where and t.base_source == "configured"


def test_a_known_layout_is_found_before_one_is_assumed(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".local/share/hermes").mkdir(parents=True)
    t = get_target("hermes", home=home)
    # the second entry of `bases`, not the first: what exists beats what would be created
    assert t.base == home / ".local/share/hermes" and t.base_source == "found"


def test_a_catalog_path_follows_the_agent_it_names(tmp_path: Path, monkeypatch):
    """`~/.hermes/skills/x` from a catalog is a guess about the layout, not an instruction.

    Honouring it literally on a machine where the agent lives elsewhere puts the component in a
    folder the agent never reads — precisely the failure discovery exists to prevent."""
    home = tmp_path / "home"
    (home / "AppData/Local/hermes").mkdir(parents=True)
    t = get_target("hermes", home=home)
    assert t.resolve_install_path("~/.hermes/skills/ldap-notes") == t.skill_dir / "ldap-notes"
    # a path matching no known layout was chosen deliberately and is left alone
    assert t.resolve_install_path(tmp_path / "elsewhere" / "x") == tmp_path / "elsewhere" / "x"
