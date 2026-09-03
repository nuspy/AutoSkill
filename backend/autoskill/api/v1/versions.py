"""Skill versions: listing, files, zip download, install docs, draft generation."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import select

from autoskill.api.v1.deps import AnyAuthUser, CurrentUser, SessionDep
from autoskill.api.v1.skills import get_skill_for
from autoskill.config import get_settings
from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.jobs import get_job_runner
from autoskill.models.project import Project, ProjectRole
from autoskill.models.review import Authorization, VersionTransition
from autoskill.models.skill import Skill
from autoskill.models.skill_version import LibraryComponent, SkillDependency, SkillVersion, StepDefinition
from autoskill.schemas.draft import FileContent, GenerateRequest, InstallDoc, StepOut, VersionDetail, VersionOut
from autoskill.schemas.review import AuthorizationOut, AuthorizeIn, TransitionIn, TransitionOut
from autoskill.services.packaging.skill_package import TEXT_EXTENSIONS
from autoskill.services.packaging.store import load_package
from autoskill.services.review.service import authorize as authorize_version
from autoskill.services.targets import get_adapter, list_targets
from autoskill.services.targets.base import InstallContext, McpServerSpec
from autoskill.services.versioning.changes import compare
from autoskill.services.versioning.state_machine import allowed_targets, transition

router = APIRouter(tags=["versions"])


async def _version(
    session, user, version_id: str, minimum: ProjectRole = ProjectRole.viewer
) -> tuple[SkillVersion, Skill]:
    version = await session.get(SkillVersion, version_id)
    if version is None:
        raise NotFound("version_not_found")
    skill = await get_skill_for(session, version.skill_id, user, minimum)
    return version, skill


@router.get("/targets")
async def targets() -> list[dict]:
    return list_targets()


@router.get("/skills/{skill_id}/versions", response_model=list[VersionOut])
async def list_versions(skill_id: str, session: SessionDep, user: CurrentUser):
    await get_skill_for(session, skill_id, user, ProjectRole.viewer)
    res = await session.execute(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.major.desc(), SkillVersion.minor.desc(), SkillVersion.patch.desc())
    )
    return res.scalars().all()


@router.post("/skills/{skill_id}/versions/generate", status_code=202)
async def generate(skill_id: str, body: GenerateRequest, session: SessionDep, user: CurrentUser) -> dict:
    skill = await get_skill_for(session, skill_id, user, ProjectRole.editor)
    if skill.development_state == "suspended":
        raise Conflict("skill_suspended")
    job = await get_job_runner().enqueue(
        "draft.generate",
        {
            "skill_id": skill_id,
            "user_id": user.id,
            "mode": body.mode,
            "instructions": body.instructions,
            "base_version_id": body.base_version_id,
            "origin": "manual" if body.mode == "new" else "trial_corrections",
            "language": user.locale,
        },
        project_id=skill.project_id,
        user_id=user.id,
    )
    return {"job_id": job.id}


@router.get("/versions/{version_id}", response_model=VersionDetail)
async def version_detail(version_id: str, session: SessionDep, user: CurrentUser):
    version, _ = await _version(session, user, version_id)
    steps = (
        (
            await session.execute(
                select(StepDefinition)
                .where(StepDefinition.skill_version_id == version.id)
                .order_by(StepDefinition.ordinal)
            )
        )
        .scalars()
        .all()
    )
    deps = (
        (await session.execute(select(SkillDependency).where(SkillDependency.skill_version_id == version.id)))
        .scalars()
        .all()
    )
    out = VersionDetail.model_validate(version)
    out.steps = [StepOut.model_validate(s) for s in steps]
    out.dependencies = [
        {"component_slug": d.component_slug, "reason": d.reason, "version_constraint": d.version_constraint}
        for d in deps
    ]
    out.build_log = version.build_log
    return out


@router.get("/versions/{version_id}/files/{path:path}", response_model=FileContent)
async def file_content(version_id: str, path: str, session: SessionDep, user: CurrentUser):
    version, skill = await _version(session, user, version_id)
    pkg = load_package(skill.name, version)
    if path not in pkg.files:
        raise NotFound("file_not_found")
    data = pkg.files[path]
    binary = not any(path.endswith(ext) for ext in TEXT_EXTENSIONS)
    return FileContent(
        path=path, content="" if binary else data.decode(errors="replace"), size=len(data), binary=binary
    )


async def _install_context(session, skill: Skill, version: SkillVersion, trial: bool = False) -> InstallContext:
    settings = get_settings()
    project = await session.get(Project, skill.project_id)
    deps = (
        (await session.execute(select(SkillDependency).where(SkillDependency.skill_version_id == version.id)))
        .scalars()
        .all()
    )
    dep_specs: list[dict] = []
    mcp_servers = [
        McpServerSpec(
            name="autoskill-companion",
            command="autoskill-companion",
            args=[],
            env_requirements=[
                {"name": "AUTOSKILL_URL", "description": f"AutoSkill server, {settings.public_url}", "secret": False},
                {
                    "name": "AUTOSKILL_API_KEY",
                    "description": "key from `autoskill login` or a project API key (telemetry:write)",
                    "secret": True,
                },
            ],
            description="checkpoints and run telemetry for AutoSkill",
            install_hint="pipx install autoskill-local",
        )
    ]
    from autoskill.models.mcp import McpServerVersion

    mv = (
        await session.execute(select(McpServerVersion).where(McpServerVersion.skill_version_id == version.id))
    ).scalar_one_or_none()
    if mv is not None:
        server_name = f"{skill.name}-tools"
        mcp_servers.append(
            McpServerSpec(
                name=server_name,
                command=server_name,
                args=[],
                env_requirements=list(mv.env_requirements),
                description=f"deterministic tools for {skill.title} ({len(mv.tools)} tools)",
                install_hint=f"pipx install ./mcp/{server_name}",
            )
        )
    for dep in deps:
        comp = (
            await session.execute(select(LibraryComponent).where(LibraryComponent.slug == dep.component_slug))
        ).scalar_one_or_none()
        if comp is None:
            continue
        install = comp.install or {}
        dep_specs.append(
            {
                "slug": comp.slug,
                "name": comp.name,
                "kind": comp.kind,
                "install_hint": install.get("hint") or comp.description,
            }
        )
        if comp.kind == "mcp_server" and (install.get("command") or install.get("url")):
            mcp_servers.append(
                McpServerSpec(
                    name=comp.slug,
                    command=install.get("command"),
                    args=install.get("args", []),
                    url=install.get("url"),
                    env_requirements=comp.env_requirements,
                    description=comp.description,
                    install_hint=install.get("hint", ""),
                )
            )
    return InstallContext(
        skill_name=skill.name,
        skill_title=skill.title,
        version=version.version,
        server_url=settings.public_url,
        project_slug=project.slug if project else "",
        mcp_servers=mcp_servers,
        dependencies=dep_specs,
        trial=trial,
        zip_url=f"{settings.public_url}/api/v1/versions/{version.id}/package.zip",
    )


@router.get("/versions/{version_id}/install/{target}", response_model=InstallDoc)
async def install_doc(version_id: str, target: str, session: SessionDep, user: CurrentUser, trial: bool = False):
    version, skill = await _version(session, user, version_id)
    try:
        adapter = get_adapter(target)
    except KeyError:
        raise ValidationFailed("unknown_target", targets=[t["id"] for t in list_targets()]) from None
    ctx = await _install_context(session, skill, version, trial=trial)
    return InstallDoc(target=target, markdown=adapter.render_install_md(ctx))


@router.get("/versions/{version_id}/package.zip")
async def package_zip(
    version_id: str, session: SessionDep, user: AnyAuthUser, targets: str | None = None, target: str | None = None
):
    version = await session.get(SkillVersion, version_id)
    if version is None:
        raise NotFound("version_not_found")
    skill = await session.get(Skill, version.skill_id)
    from autoskill.api.v1.hub import _visible_skill

    skill = await _visible_skill(session, skill.id, user)
    if version.state == "published" and target:
        from autoskill.services.distribution.install_tracking import record_installation

        await record_installation(
            session,
            user_id=user.id,
            skill_id=skill.id,
            skill_version_id=version.id,
            target_agent=target,
            channel="zip",
            state="downloaded",
        )
        await session.commit()
    pkg = load_package(skill.name, version)
    extra: dict[str, bytes] = {}
    for target in targets.split(",") if targets else ["hermes", "openclaw"]:
        try:
            adapter = get_adapter(target.strip())
        except KeyError:
            continue
        ctx = await _install_context(session, skill, version)
        extra[f"INSTALL.{adapter.id}.md"] = adapter.render_install_md(ctx).encode()
    extra["autoskill.json"] = _autoskill_json(skill, version, pkg).encode()
    extra.update(await _mcp_files(session, skill, version))
    data = pkg.to_zip(extra)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill.name}-{version.version}.zip"'},
    )


async def _mcp_files(session, skill: Skill, version: SkillVersion) -> dict[str, bytes]:
    from autoskill.models.mcp import McpServerVersion
    from autoskill.services.mcpgen.generator import load_mcp_files

    mv = (
        await session.execute(select(McpServerVersion).where(McpServerVersion.skill_version_id == version.id))
    ).scalar_one_or_none()
    if mv is None:
        return {}
    return {f"mcp/{skill.name}-tools/{path}": content for path, content in load_mcp_files(mv).items()}


def _autoskill_json(skill: Skill, version: SkillVersion, pkg) -> str:
    import json

    return json.dumps(
        {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "version_id": version.id,
            "version": version.version,
            "signature": version.signature,
            "files": version.manifest.get("files", []),
            "mcp_servers": ["autoskill-companion"],
            "server_url": get_settings().public_url,
        },
        indent=2,
    )


@router.post("/versions/{version_id}/discard", response_model=VersionOut)
async def discard(version_id: str, session: SessionDep, user: CurrentUser):
    version, skill = await _version(session, user, version_id, ProjectRole.editor)
    await transition(session, version, "discarded", actor=user, reason="discarded by author")
    if skill.latest_version_id == version.id:
        skill.latest_version_id = version.parent_version_id
    await session.commit()
    await session.refresh(version)
    return version


@router.post("/versions/{version_id}/transition", response_model=VersionOut)
async def do_transition(version_id: str, body: TransitionIn, session: SessionDep, user: CurrentUser):
    """Author-side moves: back to testing, mark tested (all steps confirmed), discard."""
    version, _ = await _version(session, user, version_id, ProjectRole.editor)
    await transition(session, version, body.to_state, actor=user, reason=body.reason)
    await session.commit()
    await session.refresh(version)
    return version


@router.get("/versions/{version_id}/transitions", response_model=list[TransitionOut])
async def transitions(version_id: str, session: SessionDep, user: CurrentUser):
    version, _ = await _version(session, user, version_id)
    res = await session.execute(
        select(VersionTransition)
        .where(VersionTransition.skill_version_id == version.id)
        .order_by(VersionTransition.created_at)
    )
    return res.scalars().all()


@router.get("/versions/{version_id}/allowed")
async def allowed(version_id: str, session: SessionDep, user: CurrentUser) -> dict:
    version, _ = await _version(session, user, version_id)
    return {"state": version.state, "allowed": allowed_targets(version.state)}


@router.get("/versions/{version_id}/diff")
async def diff(version_id: str, session: SessionDep, user: CurrentUser, to: str | None = None) -> dict:
    """Compare this version with `to` (older version id) or with its parent / the published version."""
    version, skill = await _version(session, user, version_id)
    older = None
    if to:
        older = await session.get(SkillVersion, to)
        if older is None or older.skill_id != skill.id:
            raise NotFound("version_not_found")
    elif version.parent_version_id:
        older = await session.get(SkillVersion, version.parent_version_id)
    elif skill.current_published_version_id and skill.current_published_version_id != version.id:
        older = await session.get(SkillVersion, skill.current_published_version_id)
    return await compare(session, skill, version, older)


@router.post("/versions/{version_id}/authorize", response_model=AuthorizationOut)
async def authorize(version_id: str, body: AuthorizeIn, session: SessionDep, user: CurrentUser):
    """Human authorization to publish (from approved) or deprecate (from published)."""
    version, _ = await _version(session, user, version_id, ProjectRole.editor)
    auth = await authorize_version(
        session, version, user, action=body.action, checklist=body.checklist, comment=body.comment
    )
    await session.commit()
    await session.refresh(auth)
    return auth


@router.get("/versions/{version_id}/authorizations", response_model=list[AuthorizationOut])
async def authorizations(version_id: str, session: SessionDep, user: CurrentUser):
    version, _ = await _version(session, user, version_id)
    res = await session.execute(
        select(Authorization).where(Authorization.subject_id == version.id).order_by(Authorization.created_at)
    )
    return res.scalars().all()
