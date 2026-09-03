"""Read-only git smart HTTP for published skills: /git/<project>/<skill>.git"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from autoskill.api.v1.deps import get_api_key, get_optional_user
from autoskill.core.errors import NotFound, Unauthorized
from autoskill.db.session import get_session_factory
from autoskill.models.hub import SkillRepo
from autoskill.models.project import Project
from autoskill.models.skill import Skill
from autoskill.services.distribution import git_repo
from autoskill.services.settings import get_setting

router = APIRouter(prefix="/git", tags=["git"])


async def _authorized_repo(request: Request, project_slug: str, skill_name: str) -> SkillRepo:
    async with get_session_factory()() as session:
        project = (await session.execute(select(Project).where(Project.slug == project_slug))).scalar_one_or_none()
        if project is None:
            raise NotFound("repo_not_found")
        skill = (
            await session.execute(select(Skill).where(Skill.project_id == project.id, Skill.name == skill_name))
        ).scalar_one_or_none()
        if skill is None:
            raise NotFound("repo_not_found")
        repo = await session.get(SkillRepo, skill.id)
        if repo is None:
            raise NotFound("repo_not_found")
        if repo.public_clone and await get_setting(session, "public_hub"):
            return repo
        user = await get_optional_user(request, session)
        if user is None:
            try:
                key = await get_api_key(request, session)
            except Unauthorized:
                raise Unauthorized("git_auth_required", message="Use an AutoSkill API key as the password.") from None
            if key.user_id is None and key.project_id != skill.project_id:
                raise Unauthorized("git_auth_required")
        elif skill.visibility == "private":
            from autoskill.core.permissions import require_project_role
            from autoskill.models.project import ProjectRole

            await require_project_role(session, skill.project_id, user, ProjectRole.viewer)
        return repo


@router.get("/{project_slug}/{skill_name}.git/info/refs")
async def info_refs(project_slug: str, skill_name: str, request: Request, service: str | None = None):
    repo = await _authorized_repo(request, project_slug, skill_name)
    if service != "git-upload-pack":
        return Response(status_code=403, content="read-only repository")
    body = await git_repo.advertise_refs(__import__("pathlib").Path(repo.path))
    return Response(
        content=body, media_type="application/x-git-upload-pack-advertisement", headers={"Cache-Control": "no-cache"}
    )


@router.post("/{project_slug}/{skill_name}.git/git-upload-pack")
async def upload_pack(project_slug: str, skill_name: str, request: Request):
    repo = await _authorized_repo(request, project_slug, skill_name)
    body = await request.body()
    out = await git_repo.upload_pack(__import__("pathlib").Path(repo.path), body)
    return Response(
        content=out, media_type="application/x-git-upload-pack-result", headers={"Cache-Control": "no-cache"}
    )


@router.post("/{project_slug}/{skill_name}.git/git-receive-pack")
async def receive_pack(project_slug: str, skill_name: str):
    return Response(status_code=403, content="AutoSkill repositories are read-only")
