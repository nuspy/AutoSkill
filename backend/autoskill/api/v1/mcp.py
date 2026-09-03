"""Generated MCP servers: generate, inspect, files, local check reports."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from autoskill.api.v1.deps import AnyAuthUser, CurrentUser, SessionDep
from autoskill.api.v1.skills import get_skill_for
from autoskill.core.errors import NotFound
from autoskill.core.jobs import get_job_runner
from autoskill.db.base import utcnow
from autoskill.models.mcp import McpServer, McpServerVersion
from autoskill.models.project import ProjectRole
from autoskill.models.skill_version import SkillVersion
from autoskill.schemas.common import ORMModel
from autoskill.schemas.draft import FileContent
from autoskill.services.mcpgen.generator import load_mcp_files

router = APIRouter(tags=["mcp"])


class McpVersionOut(ORMModel):
    id: str
    mcp_server_id: str
    skill_version_id: str
    version: str
    state: str
    manifest: dict
    tools: list
    env_requirements: list
    dependencies: list
    build_log: str | None
    static_report: dict
    trial_report: dict | None
    build: int
    server_name: str = ""


class TrialReportIn(BaseModel):
    ok: bool
    tools: list[dict] = Field(default_factory=list)
    tests_ok: bool | None = None
    log: list[str] = Field(default_factory=list)
    error: str | None = None
    server_dir: str | None = None


async def _mcp_for_version(
    session, user, version_id: str, minimum: ProjectRole = ProjectRole.viewer
) -> tuple[McpServerVersion | None, SkillVersion, McpServer | None]:
    version = await session.get(SkillVersion, version_id)
    if version is None:
        raise NotFound("version_not_found")
    await get_skill_for(session, version.skill_id, user, minimum)
    mv = (
        await session.execute(select(McpServerVersion).where(McpServerVersion.skill_version_id == version.id))
    ).scalar_one_or_none()
    server = await session.get(McpServer, mv.mcp_server_id) if mv else None
    return mv, version, server


def _out(mv: McpServerVersion, server: McpServer | None) -> McpVersionOut:
    out = McpVersionOut.model_validate(mv)
    out.server_name = server.name if server else ""
    return out


@router.post("/versions/{version_id}/mcp/generate", status_code=202)
async def generate(version_id: str, session: SessionDep, user: CurrentUser) -> dict:
    _, version, _ = await _mcp_for_version(session, user, version_id, ProjectRole.editor)
    skill = await get_skill_for(session, version.skill_id, user, ProjectRole.editor)
    job = await get_job_runner().enqueue(
        "mcp.generate", {"version_id": version.id, "user_id": user.id}, project_id=skill.project_id, user_id=user.id
    )
    return {"job_id": job.id}


@router.get("/versions/{version_id}/mcp", response_model=McpVersionOut | None)
async def detail(version_id: str, session: SessionDep, user: CurrentUser):
    mv, _, server = await _mcp_for_version(session, user, version_id)
    return _out(mv, server) if mv else None


@router.get("/versions/{version_id}/mcp/files/{path:path}", response_model=FileContent)
async def mcp_file(version_id: str, path: str, session: SessionDep, user: CurrentUser):
    mv, _, _ = await _mcp_for_version(session, user, version_id)
    if mv is None:
        raise NotFound("mcp_not_found")
    files = load_mcp_files(mv)
    if path not in files:
        raise NotFound("file_not_found")
    data = files[path]
    return FileContent(path=path, content=data.decode(errors="replace"), size=len(data))


@router.post("/mcp/versions/{mcp_version_id}/trial-report", response_model=McpVersionOut)
async def trial_report(mcp_version_id: str, body: TrialReportIn, session: SessionDep, user: AnyAuthUser):
    """Sent by `autoskill mcp check` after installing and listing the tools on the user's machine."""
    mv = await session.get(McpServerVersion, mcp_version_id)
    if mv is None:
        raise NotFound("mcp_not_found")
    version = await session.get(SkillVersion, mv.skill_version_id)
    await get_skill_for(session, version.skill_id, user, ProjectRole.viewer)
    expected = {t["name"] for t in mv.tools}
    listed = {t.get("name") for t in body.tools}
    ok = body.ok and expected <= listed
    mv.trial_report = {
        **body.model_dump(),
        "checked_at": utcnow().isoformat(),
        "missing_tools": sorted(expected - listed),
        "by_user": user.id,
    }
    mv.state = "trial_passed" if ok else "trial_failed"
    await session.commit()
    await session.refresh(mv)
    server = await session.get(McpServer, mv.mcp_server_id)
    return _out(mv, server)
