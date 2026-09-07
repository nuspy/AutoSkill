"""The script wrapper: same tool modules, reached by a command line instead of a protocol."""

import json
import subprocess
import sys

from autoskill.services.mcpgen.spec import McpSpec, McpTool, ToolParam
from autoskill.services.scriptgen.assemble import assemble_scripts, render_usage


def spec() -> McpSpec:
    return McpSpec(
        description="Tools for the invoice check.",
        dependencies=[],
        tools=[
            McpTool(
                name="sum_column",
                step_key="add-sums-under-lists",
                description="Sum a column and return the total.",
                side_effects="read_only",
                params=[
                    ToolParam(name="values", type="array", description="Numbers to add", required=True),
                    ToolParam(name="label", type="string", description="Name of the total", required=False),
                ],
                code="def run(**kwargs) -> dict:\n"
                "    values = kwargs.get('values') or []\n"
                "    return {'label': kwargs.get('label') or 'total', 'total': sum(values)}\n",
            ),
            McpTool(
                name="save_file",
                step_key="save-workbook",
                description="Write the workbook back to disk.",
                side_effects="irreversible",
                params=[ToolParam(name="path", type="string", description="File to write", required=True)],
                code="def run(**kwargs) -> dict:\n    return {'written': kwargs.get('path'), 'dry_run': kwargs.get('dry_run')}\n",
            ),
        ],
    )


def write_package(tmp_path) -> str:
    files = assemble_scripts("invoices-tools", "1.0.0", spec(), skill_name="invoices")
    for path, content in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return str(tmp_path)


def run_cli(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "invoices_tools.cli", *args],
        cwd=root, capture_output=True, text=True, timeout=60,
    )


def test_the_package_has_a_cli_and_no_server(tmp_path):
    files = assemble_scripts("invoices-tools", "1.0.0", spec(), skill_name="invoices")
    assert "invoices_tools/cli.py" in files
    assert "invoices_tools/server.py" not in files  # nothing speaks the protocol here
    assert b"mcp>=" not in files["pyproject.toml"]  # and nothing depends on it
    assert b"invoices-tools = \"invoices_tools.cli:main\"" in files["pyproject.toml"]
    # the tool modules are the ones mcpgen writes, untouched
    assert b"def run(" in files["invoices_tools/tools/sum_column.py"]


def test_list_tools_matches_the_mcp_output(tmp_path):
    out = run_cli(write_package(tmp_path), "--list-tools")
    assert out.returncode == 0, out.stderr
    assert [t["step_key"] for t in json.loads(out.stdout)] == ["add-sums-under-lists", "save-workbook"]


def test_help_documents_the_parameters(tmp_path):
    out = run_cli(write_package(tmp_path), "sum_column", "--help")
    assert out.returncode == 0, out.stderr
    assert "--values" in out.stdout and "Numbers to add" in out.stdout


def test_running_a_step_prints_json(tmp_path):
    out = run_cli(write_package(tmp_path), "sum_column", "--values", "[10, 20, 30]", "--label", "sum")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"label": "sum", "total": 60}


def test_effects_are_described_unless_apply_is_given(tmp_path):
    root = write_package(tmp_path)
    dry = run_cli(root, "save_file", "--path", "book.xlsx")
    assert json.loads(dry.stdout)["dry_run"] is True

    # irreversible: without the token the command refuses to act for real
    real = run_cli(root, "save_file", "--path", "book.xlsx", "--apply")
    assert real.returncode == 1
    assert "confirmation_token" in real.stderr

    ok = run_cli(root, "save_file", "--path", "book.xlsx", "--apply", "--confirmation-token", "t-123")
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["dry_run"] is False


def test_a_failing_step_exits_non_zero_with_the_error(tmp_path):
    out = run_cli(write_package(tmp_path), "sum_column", "--values", '["not", "numbers"]')
    assert out.returncode == 1
    assert "error" in json.loads(out.stderr)


def test_usage_lines_tell_the_agent_how_to_call_each_step():
    usage = render_usage("invoices-tools", spec().tools)
    assert "invoices-tools sum_column --values <array>" in usage
    assert "--apply" in usage  # the effectful step says how to perform it for real
    assert "confirmation-token" in usage


async def test_script_delivery_end_to_end(app_client):
    """The default path: the same steps arrive as commands, and nothing is registered with the agent."""
    import io
    import zipfile

    from autoskill.core.jobs import get_job_runner
    from autoskill.llm.fake import FakeLlmProvider, Scripted
    from autoskill.llm.registry import set_fake_provider
    from tests.test_interview import setup_project
    from tests.test_mcpgen import spec_dict
    from tests.test_trials import make_draft

    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)

        # scripts are the default: no need to ask for them
        analysis = (await app_client.get(f"/api/v1/versions/{version['id']}/delivery", headers=headers)).json()
        assert analysis["delivery"] == "script"

        fake.script(Scripted(purpose="author", json=spec_dict()))
        gen = await app_client.post(f"/api/v1/versions/{version['id']}/mcp/generate", headers=headers)
        assert gen.status_code == 202
        await get_job_runner().wait_all()

        files = (await app_client.get(f"/api/v1/versions/{version['id']}/mcp", headers=headers)).json()
        assert files is not None, "generation produced nothing"
        paths = {f["path"] for f in files["manifest"]["files"]}
        assert any(p.endswith("/cli.py") for p in paths), paths
        assert not any(p.endswith("/server.py") for p in paths), "a command line needs no server"
        assert "USAGE.md" in paths  # the lines that tell the agent how to call each step

        zip_res = await app_client.get(
            f"/api/v1/versions/{version['id']}/package.zip?targets=hermes", headers=headers
        )
        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
            names = set(zf.namelist())
        assert any(n.endswith("/cli.py") for n in names)

        install = (await app_client.get(f"/api/v1/versions/{version['id']}/install/hermes", headers=headers)).json()[
            "markdown"
        ]
        assert "## Steps of this skill" in install
        assert "--list-tools" in install and "--help" in install
        # the companion is still registered — it is what carries the telemetry — but the skill's
        # own package is not: its steps are commands, and appear only in the section above
        # (the package is still in the download table: it has to be installed, just not registered)
        registration = install.split("register the MCP servers")[1]
        assert "autoskill-companion" in registration
        assert "-tools" not in registration
    finally:
        set_fake_provider(None)
