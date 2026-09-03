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

    reg = target.register_mcp(McpRegistration(name="autoskill-companion", command="autoskill-companion", env={"AUTOSKILL_URL": "http://x"}))
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
