import io
import zipfile

from autoskill.schemas.draft import DraftFile, DraftSpec, DraftStep
from autoskill.services.drafting.assemble import assemble_package, trial_mode_for
from autoskill.services.packaging.skill_package import SkillPackage, parse_frontmatter
from autoskill.services.targets import get_adapter, list_targets
from autoskill.services.targets.base import InstallContext, McpServerSpec

GOOD_MD = """---
name: invoice-check
description: Checks supplier invoices against purchase orders every Monday. Use when asked to verify invoices.
metadata:
  version: "0.1.0"
---
# Invoice check

## Steps
<!-- step:open -->
### 1. Open
Open scripts/extract.py output.
"""


def make(name="invoice-check", md=GOOD_MD, extra=None):
    files = {"SKILL.md": md, "scripts/extract.py": "print('hi')\n"}
    files.update(extra or {})
    return SkillPackage.from_files(name, files)


def codes(pkg):
    return {i.code for i in pkg.validate().issues}


def test_valid_package_passes():
    report = make().validate()
    assert report.ok, report.as_dict()


def test_name_rules():
    assert "invalid_name" in codes(make(name="Invoice-Check", md=GOOD_MD.replace("invoice-check", "Invoice-Check")))
    assert "invalid_name" in codes(make(name="-bad", md=GOOD_MD.replace("invoice-check", "-bad")))
    assert "invalid_name" in codes(make(name="a--b", md=GOOD_MD.replace("invoice-check", "a--b")))
    assert "name_mismatch" in codes(make(name="other-name"))


def test_description_metadata_and_body_rules():
    assert "bad_description" in codes(
        make(
            md=GOOD_MD.replace(
                "description: Checks supplier invoices against purchase orders every Monday. Use when asked to verify invoices.",
                "description: ''",
            )
        )
    )
    assert "bad_metadata" in codes(make(md=GOOD_MD.replace('  version: "0.1.0"', "  version: 1")))
    assert "empty_body" in codes(make(md=GOOD_MD.split("---\n# Invoice")[0] + "---\n"))
    assert "bad_frontmatter" in codes(make(md="no frontmatter here"))


def test_references_secrets_syntax_and_paths():
    assert "missing_reference" in codes(make(md=GOOD_MD + "\nSee [ref](references/missing.md)\n"))
    assert "secret_detected" in codes(
        make(extra={"references/notes.md": "api_key = 'sk-abcdefghijklmnopqrstuvwxyz123456'\n"})
    )
    assert "python_syntax" in codes(make(extra={"scripts/broken.py": "def (:\n"}))
    assert "bad_path" in codes(make(extra={"../escape.md": "x"}))


def test_zip_round_trip_manifest_and_diff():
    pkg = make()
    data = pkg.to_zip({"INSTALL.hermes.md": b"# install"})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
    assert "invoice-check/SKILL.md" in names and "invoice-check/INSTALL.hermes.md" in names
    back = SkillPackage.from_zip(data)
    assert back.name == "invoice-check" and back.read_text("SKILL.md") == GOOD_MD
    manifest = pkg.manifest()
    assert {f["path"] for f in manifest["files"]} == {"SKILL.md", "scripts/extract.py"}
    assert pkg.sign() == make().sign()
    newer = make(extra={"references/a.md": "x"})
    newer.write("SKILL.md", GOOD_MD + "\nmore\n")
    assert newer.diff(pkg) == {"added": ["references/a.md"], "removed": [], "changed": ["SKILL.md"]}


def sample_spec() -> DraftSpec:
    return DraftSpec(
        description="Checks supplier invoices against purchase orders every Monday. Use when the user asks to verify or flag invoices.",
        overview="# Invoice check\n\nVerifies invoices.\n\nInputs: the invoices spreadsheet.",
        steps=[
            DraftStep(
                key="open-sheet",
                title="Open the sheet",
                instruction="Open Invoices.xlsx from the shared drive.",
                kind="deterministic",
                side_effects="read_only",
                restore_strategy="none",
                data_source_refs=["invoices"],
            ),
            DraftStep(
                key="flag",
                title="Flag anomalies",
                instruction="Flag rows over 1000.",
                kind="generative",
                side_effects="reversible",
                restore_strategy="backup_file",
                success_criteria="every row over 1000 is flagged",
            ),
            DraftStep(
                key="send",
                title="Email accounting",
                instruction="Send the list to accounting.",
                kind="deterministic",
                side_effects="irreversible",
                network=True,
                restore_strategy="none",
                library_component_slug="email-mcp",
            ),
        ],
        edge_cases_markdown="If the sheet is empty, stop.",
        files=[DraftFile(path="references/columns.md", content="| number | amount |")],
        changelog="first draft",
    )


def test_assemble_package_is_deterministic_and_valid():
    pkg = assemble_package(
        skill_name="invoice-check", version="0.1.0", spec=sample_spec(), metadata={"author": "autoskill"}
    )
    again = assemble_package(
        skill_name="invoice-check", version="0.1.0", spec=sample_spec(), metadata={"author": "autoskill"}
    )
    assert pkg.files == again.files
    report = pkg.validate()
    assert report.ok, report.as_dict()
    fm, body = parse_frontmatter(pkg.skill_md)
    assert (
        fm["name"] == "invoice-check"
        and fm["metadata"]["version"] == "0.1.0"
        and fm["metadata"]["author"] == "autoskill"
    )
    assert "<!-- step:open-sheet -->" in body and "<!-- step:send -->" in body
    assert "IRREVERSIBLE" in body and "### 3. Email accounting ⚠" in body
    assert "autoskill-companion" in body and "start_run" in body and "approve_and_authorize_next" in body
    assert "Component: email-mcp" in body
    assert "references/columns.md" in pkg.files
    assert trial_mode_for(sample_spec().steps[0]) == "real"
    assert trial_mode_for(sample_spec().steps[1]) == "sandbox_copy"
    assert trial_mode_for(sample_spec().steps[2]) == "simulate"


def test_target_adapters_render_install_docs():
    ids = {t["id"] for t in list_targets()}
    assert ids == {"hermes", "openclaw", "claude_code", "codex", "antigravity"}
    spec = McpServerSpec(
        name="autoskill-companion",
        command="autoskill-companion",
        env_requirements=[{"name": "AUTOSKILL_API_KEY", "description": "key", "secret": True}],
    )
    ctx = InstallContext(
        skill_name="invoice-check",
        skill_title="Invoice check",
        version="1.2.0",
        server_url="https://autoskill.example",
        project_slug="ops",
        mcp_servers=[spec],
        dependencies=[
            {"slug": "email-mcp", "name": "Email MCP", "kind": "mcp_server", "install_hint": "pipx install email-mcp"}
        ],
        git_url="autoskill.example/git/ops/invoice-check.git",
    )
    hermes = get_adapter("hermes").render_install_md(ctx)
    assert "~/.hermes/skills/invoice-check/" in hermes and "mcp_servers:" in hermes and "type: stdio" in hermes
    assert "AUTOSKILL_API_KEY: <AUTOSKILL_API_KEY>" in hermes and "Email MCP" in hermes
    openclaw = get_adapter("openclaw").render_install_md(ctx)
    assert "openclaw skills install git:autoskill.example/git/ops/invoice-check.git@v1.2.0" in openclaw
    assert "mcporter.json" in openclaw and '"mcpServers"' in openclaw
    codex = get_adapter("codex").render_install_md(ctx)
    assert "[mcp_servers.autoskill-companion]" in codex and "[mcp_servers.autoskill-companion.env]" in codex
    claude = get_adapter("claude_code").render_install_md(ctx)
    assert ".mcp.json" in claude and "~/.claude/skills/invoice-check/" in claude
    anti = get_adapter("antigravity").render_install_md(ctx)
    assert ".agents/skills/invoice-check/" in anti
    trial = get_adapter("hermes").render_install_md(
        InstallContext(skill_name="x", skill_title="X", version="0.1.0", server_url="s", project_slug="p", trial=True)
    )
    assert "Trial installation" in trial and "autoskill trial install x@0.1.0 --target hermes" in trial
