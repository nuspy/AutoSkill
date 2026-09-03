"""MCP generation from deterministic steps: static checks, package assembly, integration in zip/install docs."""

import io
import zipfile

from autoskill.core.jobs import get_job_runner
from autoskill.llm.fake import FakeLlmProvider, Scripted
from autoskill.llm.registry import set_fake_provider
from autoskill.services.mcpgen.assemble import assemble_mcp
from autoskill.services.mcpgen.spec import McpSpec, check_python_source
from tests.test_interview import setup_project
from tests.test_trials import make_draft

GOOD_TOOL = """
import csv
from pathlib import Path


def run(path: str, dry_run: bool = True, **kwargs) -> dict:
    rows = list(csv.DictReader(Path(path).open()))
    flagged = [r for r in rows if float(r.get("amount", 0) or 0) > 1000]
    return {"summary": f"{len(flagged)} rows over 1000", "flagged": flagged, "dry_run": dry_run}
"""

SEND_TOOL = """
import os
import smtplib


def run(recipient: str, body: str, dry_run: bool = True, confirmation_token: str | None = None, **kwargs) -> dict:
    if dry_run:
        return {"summary": f"would email {recipient}", "body": body}
    with smtplib.SMTP(os.environ["SMTP_HOST"]) as s:
        s.sendmail("bot@corp", [recipient], body)
    return {"summary": f"emailed {recipient}"}
"""


def spec_dict(bad: bool = False) -> dict:
    return {
        "description": "Tools for the invoice check skill",
        "tools": [
            {
                "name": "open_sheet",
                "step_key": "open-sheet",
                "description": "Read the invoices sheet",
                "side_effects": "read_only",
                "params": [{"name": "path", "type": "string", "description": "file path"}],
                "code": GOOD_TOOL
                if not bad
                else "import subprocess\n\ndef run(**kwargs):\n    return subprocess.run(['ls'])\n",
            },
            {
                "name": "send",
                "step_key": "send",
                "description": "Email the list",
                "side_effects": "irreversible",
                "network": True,
                "params": [{"name": "recipient", "type": "string"}, {"name": "body", "type": "string"}],
                "code": SEND_TOOL,
            },
            {
                "name": "ghost",
                "step_key": "not-a-step",
                "description": "dropped",
                "code": "def run(**kwargs):\n    return {}\n",
            },
        ],
        "env_requirements": [{"name": "SMTP_HOST", "description": "smtp server", "secret": False}],
        "dependencies": ["pandas"],
    }


def test_static_checks_catch_forbidden_code():
    codes = {
        i.code
        for i in check_python_source(
            "t.py",
            "import subprocess\nimport ctypes\n\ndef run(**k):\n    eval('1')\n    os.system('x')\n",
            network_allowed=False,
        )
    }
    assert {"forbidden_import", "forbidden_call"} <= codes
    assert {
        i.code
        for i in check_python_source("t.py", "import httpx\n\ndef run(**k):\n    return {}\n", network_allowed=False)
    } == {"network_not_declared"}
    assert check_python_source("t.py", "import httpx\n\ndef run(**k):\n    return {}\n", network_allowed=True) == []
    assert {
        i.code
        for i in check_python_source("t.py", "import numpy\n\ndef run(**k):\n    return {}\n", network_allowed=False)
    } == {"unknown_import"}
    assert {i.code for i in check_python_source("t.py", "x = 1\n", network_allowed=False)} == {"missing_run"}
    assert "secret_detected" in {
        i.code
        for i in check_python_source(
            "t.py", "api_key = 'sk_abcdefghijklmnop'\n\ndef run(**k):\n    return {}\n", network_allowed=False
        )
    }


def test_assemble_mcp_files_compile_and_guard_irreversible():
    d = spec_dict()
    d["tools"] = d["tools"][:2]
    spec = McpSpec.model_validate(d)
    files = assemble_mcp("invoice-check-tools", "0.1.0", spec)
    assert {
        "pyproject.toml",
        "README.md",
        "invoice_check_tools/server.py",
        "invoice_check_tools/tools/open_sheet.py",
        "invoice_check_tools/tools/send.py",
        "tests/test_tools.py",
    } <= set(files)
    for path, content in files.items():
        if path.endswith(".py"):
            compile(content.decode(), path, "exec")
    server = files["invoice_check_tools/server.py"].decode()
    assert "def send(recipient: str, body: str, dry_run: bool = True, confirmation_token: str | None = None)" in server
    assert "_require_confirmation" in server and "--list-tools" in server
    assert "_require_confirmation" in files["invoice_check_tools/tools/send.py"].decode()
    assert 'invoice-check-tools = "invoice_check_tools.server:main"' in files["pyproject.toml"].decode()


async def test_generate_mcp_end_to_end(app_client):
    user, headers, project = await setup_project(app_client)
    fake = FakeLlmProvider()
    set_fake_provider(fake)
    try:
        skill_id, version = await make_draft(app_client, headers, project, fake)
        assert (await app_client.get(f"/api/v1/versions/{version['id']}/mcp", headers=headers)).json() is None
        # first attempt has forbidden code -> repaired on the second attempt
        fake.script(Scripted(purpose="author", json=spec_dict(bad=True)), Scripted(purpose="author", json=spec_dict()))
        gen = await app_client.post(f"/api/v1/versions/{version['id']}/mcp/generate", headers=headers)
        assert gen.status_code == 202
        await get_job_runner().wait_all()
        mv = (await app_client.get(f"/api/v1/versions/{version['id']}/mcp", headers=headers)).json()
        assert mv is not None, "mcp version should exist"
        assert mv["state"] == "built" and mv["server_name"] == "invoice-check-tools"
        assert [t["name"] for t in mv["tools"]] == ["open_sheet", "send"]  # ghost dropped
        send = next(t for t in mv["tools"] if t["name"] == "send")
        assert send["side_effects"] == "irreversible" and "confirmation_token" in send["input_schema"]["properties"]
        assert "attempt 1: 2 static errors" in mv["build_log"] or "attempt 1: 1 static errors" in mv["build_log"]
        assert "attempt 2: ok" in mv["build_log"]
        assert mv["static_report"]["ok"] is True and mv["env_requirements"][0]["name"] == "SMTP_HOST"
        f = (
            await app_client.get(
                f"/api/v1/versions/{version['id']}/mcp/files/invoice_check_tools/tools/open_sheet.py", headers=headers
            )
        ).json()
        assert "def run(" in f["content"]
        # steps now reference the tools and SKILL.md has a Tools section
        vd = (await app_client.get(f"/api/v1/versions/{version['id']}", headers=headers)).json()
        assert {s["key"]: s["mcp_tool_name"] for s in vd["steps"]} == {
            "open-sheet": "open_sheet",
            "flag": None,
            "send": "send",
        }
        md = (await app_client.get(f"/api/v1/versions/{version['id']}/files/SKILL.md", headers=headers)).json()[
            "content"
        ]
        assert (
            "## Tools (MCP server `invoice-check-tools`)" in md
            and "`send` for step `send`" in md
            and "confirmation_token" in md
        )
        assert vd["build"] == 2
        # zip and install docs include the server
        zip_res = await app_client.get(f"/api/v1/versions/{version['id']}/package.zip?targets=hermes", headers=headers)
        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
            names = set(zf.namelist())
        assert (
            "invoice-check/mcp/invoice-check-tools/pyproject.toml" in names
            and "invoice-check/mcp/invoice-check-tools/invoice_check_tools/server.py" in names
        )
        install = (await app_client.get(f"/api/v1/versions/{version['id']}/install/hermes", headers=headers)).json()[
            "markdown"
        ]
        assert (
            "invoice-check-tools" in install
            and "SMTP_HOST" in install
            and "/mcp/invoice-check-tools.zip" in install
            and "pipx install http" in install
        )
        # local check report
        rep = await app_client.post(
            f"/api/v1/mcp/versions/{mv['id']}/trial-report",
            json={"ok": True, "tools": [{"name": "open_sheet"}, {"name": "send"}], "tests_ok": True},
            headers=headers,
        )
        assert rep.status_code == 200 and rep.json()["state"] == "trial_passed"
        bad = await app_client.post(
            f"/api/v1/mcp/versions/{mv['id']}/trial-report",
            json={"ok": True, "tools": [{"name": "open_sheet"}]},
            headers=headers,
        )
        assert bad.json()["state"] == "trial_failed" and bad.json()["trial_report"]["missing_tools"] == ["send"]
        # both attempts failing -> job fails, nothing stored beyond the first build
        fake.script(
            Scripted(purpose="author", json=spec_dict(bad=True)), Scripted(purpose="author", json=spec_dict(bad=True))
        )
        await app_client.post(f"/api/v1/versions/{version['id']}/mcp/generate", headers=headers)
        await get_job_runner().wait_all()
        jobs = (await app_client.get("/api/v1/admin/jobs?status=failed", headers=headers)).json()["items"]
        assert any("static checks" in (j["error"] or "") for j in jobs)
    finally:
        set_fake_provider(None)
