"""Generate an MCP server for a skill version from its deterministic steps."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound
from autoskill.core.events import emit, project_channel
from autoskill.llm.provider import ChatMessage, ChatRequest, LlmError
from autoskill.llm.registry import get_provider
from autoskill.llm.structured import structured
from autoskill.llm.usage import record_usage
from autoskill.models.interview import KnowledgeDoc
from autoskill.models.mcp import McpServer, McpServerVersion
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.prompts import render
from autoskill.services.mcpgen.assemble import assemble_mcp, input_schema, package_name
from autoskill.services.mcpgen.spec import ALLOWED_TOP_LEVEL_IMPORTS, McpSpec, StaticIssue, check_python_source
from autoskill.services.memory.context import memory_context
from autoskill.services.storage.content_store import get_content_store

ALLOWED_PIP = {
    "pandas",
    "openpyxl",
    "httpx",
    "pyyaml",
    "python-dateutil",
    "pydantic",
    "requests",
    "xlrd",
    "python-docx",
    "pypdf",
    "sqlalchemy",
    "psycopg[binary]",
    "pymysql",
    "ldap3",
    "icalendar",
}


def server_name_for(skill: Skill) -> str:
    return f"{skill.name}-tools"[:80]


def static_check(files: dict[str, bytes], spec: McpSpec) -> list[StaticIssue]:
    issues: list[StaticIssue] = []
    network_by_tool = {t.name: t.network for t in spec.tools}
    for path, content in files.items():
        if not path.endswith(".py"):
            continue
        tool_name = path.rsplit("/", 1)[-1][:-3] if "/tools/" in path and not path.endswith("__init__.py") else None
        network_allowed = network_by_tool.get(tool_name, True) if tool_name else True
        source = content.decode(errors="replace")
        if tool_name:
            issues.extend(check_python_source(path, source, network_allowed=network_allowed))
        else:
            try:
                compile(source, path, "exec")
            except SyntaxError as exc:
                issues.append(StaticIssue(level="error", code="python_syntax", message=f"{path}: {exc.msg}", path=path))
    for dep in spec.dependencies:
        if dep.split("[")[0].lower() not in {d.split("[")[0] for d in ALLOWED_PIP}:
            issues.append(
                StaticIssue(
                    level="error",
                    code="dependency_not_allowed",
                    message=f"dependency {dep!r} is not in the allowed list",
                    path="pyproject.toml",
                )
            )
    return issues


async def generate_mcp(
    session: AsyncSession, *, version_id: str, user_id: str | None, progress=None
) -> McpServerVersion:
    version = await session.get(SkillVersion, version_id)
    if version is None:
        raise NotFound("version_not_found")
    skill = await session.get(Skill, version.skill_id)
    assert skill is not None
    if version.state not in ("draft", "testing", "tested", "changes_requested"):
        raise Conflict("version_not_editable", state=version.state)
    steps = (
        (
            await session.execute(
                select(StepDefinition)
                .where(StepDefinition.skill_version_id == version.id, StepDefinition.kind == "deterministic")
                .order_by(StepDefinition.ordinal)
            )
        )
        .scalars()
        .all()
    )
    if not steps:
        raise Conflict("no_deterministic_steps", message="This version has no deterministic steps to turn into tools.")
    knowledge = (
        await session.get(KnowledgeDoc, version.knowledge_snapshot_id) if version.knowledge_snapshot_id else None
    )
    server_name = server_name_for(skill)
    provider, provider_id = await get_provider(session, skill.project_id, "author")
    memory = await memory_context(session, skill.id, budget_tokens=1500)
    system = render(
        "mcp_system", allowed=", ".join(sorted(ALLOWED_TOP_LEVEL_IMPORTS - {"os", "shutil", "tempfile", "glob"}))
    )
    repair: list[str] = []
    files: dict[str, bytes] = {}
    spec: McpSpec | None = None
    issues: list[StaticIssue] = []
    log: list[str] = []
    if progress:
        await progress(15, "writing tools")
    for attempt in range(1, 3):
        prompt = render(
            "mcp_generate",
            skill_title=skill.title,
            skill_name=skill.name,
            version=version.version,
            server_name=server_name,
            steps=steps,
            knowledge_json=json.dumps(knowledge.doc if knowledge else {}, ensure_ascii=False)[:12000],
            memory=memory,
            repair=repair,
        )
        result = await structured(
            provider,
            ChatRequest(
                messages=[ChatMessage(role="system", content=system), ChatMessage(role="user", content=prompt)],
                temperature=0.1,
                max_tokens=8000,
                seed=5,
                purpose="author",
            ),
            McpSpec,
        )
        await record_usage(session, skill.project_id, provider_id, result.usage)
        spec = result.value
        step_map = {s.key: s for s in steps}
        # code has the last word on side effects / network: copy from the step definitions
        for tool in spec.tools:
            step = step_map.get(tool.step_key)
            if step is not None:
                tool.side_effects = step.side_effects if step.side_effects != "unknown" else "reversible"
                tool.network = step.network
        spec.tools = [t for t in spec.tools if t.step_key in step_map]
        if not spec.tools:
            raise LlmError("mcp author produced no tool for the deterministic steps")
        files = assemble_mcp(server_name, version.version, spec)
        issues = static_check(files, spec)
        errors = [i for i in issues if i.level == "error"]
        log.append(
            f"attempt {attempt}: {'ok' if not errors else f'{len(errors)} static errors'} ({len(spec.tools)} tools)"
        )
        if not errors:
            break
        repair = [i.message for i in errors]
    assert spec is not None
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise LlmError("mcp generation failed static checks: " + "; ".join(e.message for e in errors[:5]))
    if progress:
        await progress(80, "saving")
    store = get_content_store()
    manifest = {"files": [{"path": p, "hash": store.put(c), "size": len(c)} for p, c in sorted(files.items())]}
    server = (await session.execute(select(McpServer).where(McpServer.skill_id == skill.id))).scalar_one_or_none()
    if server is None:
        server = McpServer(project_id=skill.project_id, skill_id=skill.id, name=server_name)
        session.add(server)
        await session.flush()
    mv = (
        await session.execute(select(McpServerVersion).where(McpServerVersion.skill_version_id == version.id))
    ).scalar_one_or_none()
    tools_json = [
        {
            "name": t.name,
            "step_key": t.step_key,
            "description": t.description,
            "side_effects": t.side_effects,
            "network": t.network,
            "input_schema": input_schema(t),
        }
        for t in spec.tools
    ]
    if mv is None:
        mv = McpServerVersion(mcp_server_id=server.id, skill_version_id=version.id, version=version.version, build=1)
        session.add(mv)
    else:
        mv.build += 1
    mv.state = "built"
    mv.manifest = manifest
    mv.tools = tools_json
    mv.env_requirements = [e.model_dump() for e in spec.env_requirements]
    mv.dependencies = spec.dependencies
    mv.draft_spec = spec.model_dump()
    mv.build_log = "\n".join(log)
    mv.static_report = {"ok": True, "issues": [i.model_dump() for i in issues]}
    mv.trial_report = None
    await session.flush()
    # link steps to tools and rebuild the skill package so SKILL.md mentions them
    by_step = {t.step_key: t.name for t in spec.tools}
    for s in steps:
        s.mcp_tool_name = by_step.get(s.key)
    from autoskill.services.trials.sync import rebuild_package

    await rebuild_package(session, version)
    await session.commit()
    await emit(
        project_channel(skill.project_id),
        "mcp.built",
        {"skill_id": skill.id, "version_id": version.id, "tools": len(spec.tools)},
    )
    return mv


def load_mcp_files(mv: McpServerVersion) -> dict[str, bytes]:
    store = get_content_store()
    return {f["path"]: store.get(f["hash"]) for f in mv.manifest.get("files", [])}


def mcp_signature(mv: McpServerVersion) -> str:
    return hashlib.sha256(json.dumps(mv.manifest.get("files", []), sort_keys=True).encode()).hexdigest()


__all__ = ["generate_mcp", "load_mcp_files", "mcp_signature", "package_name", "server_name_for", "static_check"]
