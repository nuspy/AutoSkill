"""Skill versions: listing, files, zip download, install docs, draft generation."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import select

from autoskill.api.v1.deps import AnyAuthUser, CurrentUser, SessionDep
from autoskill.api.v1.skills import get_skill_for
from autoskill.core.audit import record_audit
from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.jobs import get_job_runner
from autoskill.db.base import utcnow
from autoskill.models.hub import DownloadGrant
from autoskill.models.project import Project, ProjectRole
from autoskill.models.review import Authorization, VersionTransition
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillDependency, SkillVersion, StepDefinition
from autoskill.schemas.bundle import DownloadLinkIn, DownloadLinkOut
from autoskill.schemas.draft import FileContent, GenerateRequest, InstallDoc, StepOut, VersionDetail, VersionOut
from autoskill.schemas.review import AuthorizationOut, AuthorizeIn, TransitionIn, TransitionOut
from autoskill.services.distribution import bundle as bundles
from autoskill.services.packaging.skill_package import TEXT_EXTENSIONS
from autoskill.services.packaging.store import load_package
from autoskill.services.review.service import authorize as authorize_version
from autoskill.services.targets import get_adapter, list_targets
from autoskill.services.targets.base import InstallContext
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


async def _bundle_for(session, skill: Skill, version: SkillVersion, user, *, trial=None):
    """Bundle with URLs a reader can actually use: the user's active download link when one exists,
    otherwise the public hub address (valid only for public skills)."""
    project = await session.get(Project, skill.project_id)
    if trial is not None:
        grant = await bundles.trial_grant(session, trial)
        if grant is not None:
            return await bundles.build_bundle(
                session,
                skill=skill,
                version=version,
                base_url=bundles.grant_base_url(bundles.grant_token(grant)),
                kind="trial",
                trial=trial,
            )
    grant = (
        (
            await session.execute(
                select(DownloadGrant)
                .where(
                    DownloadGrant.skill_version_id == version.id,
                    DownloadGrant.kind == "version",
                    DownloadGrant.created_by == user.id,
                    DownloadGrant.revoked_at.is_(None),
                )
                .order_by(DownloadGrant.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if grant is not None and bundles.grant_active(grant, None):
        return await bundles.build_bundle(
            session,
            skill=skill,
            version=version,
            base_url=bundles.grant_base_url(bundles.grant_token(grant)),
            kind="version",
            expires_at=grant.expires_at,
            trial=trial,
        )
    return await bundles.build_bundle(
        session,
        skill=skill,
        version=version,
        base_url=bundles.hub_base_url(project.slug if project else "", skill.name, version.version),
        kind="hub",
        trial=trial,
    )


async def _install_context(
    session, skill: Skill, version: SkillVersion, trial: bool = False, user=None
) -> InstallContext:
    """Kept for callers that only need a rendering context (hub git publish)."""
    project = await session.get(Project, skill.project_id)
    bundle = await bundles.build_bundle(
        session,
        skill=skill,
        version=version,
        base_url=bundles.hub_base_url(project.slug if project else "", skill.name, version.version),
        kind="hub",
    )
    ctx = bundles.install_context(bundle, "hermes", project.slug if project else "")
    ctx.trial = trial
    return ctx


@router.get("/versions/{version_id}/install/{target}", response_model=InstallDoc)
async def install_doc(version_id: str, target: str, session: SessionDep, user: CurrentUser, trial: bool = False):
    version, skill = await _version(session, user, version_id)
    try:
        get_adapter(target)
    except KeyError:
        raise ValidationFailed("unknown_target", targets=[t["id"] for t in list_targets()]) from None
    bundle = await _bundle_for(session, skill, version, user)
    project = await session.get(Project, skill.project_id)
    ctx = bundles.install_context(bundle, target, project.slug if project else "")
    ctx.trial = trial
    return InstallDoc(
        target=target,
        markdown=get_adapter(target).render_install_md(ctx),
        bundle_url=bundle.install_md_urls.get(target, bundle.bundle_url),
        manifest_url=bundle.manifest_url,
        public=bundle.kind == "hub",
    )


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
    bundle = await _bundle_for(session, skill, version, user)
    wanted = [t.strip() for t in targets.split(",")] if targets else None
    data = await bundles.skill_zip(session, skill, version, bundle, targets=wanted)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill.name}-{version.version}.zip"'},
    )


# --- download links (capability URLs for agents) ----------------------------------------


def _link_out(grant: DownloadGrant) -> DownloadLinkOut:
    bundle_url, manifest_url = bundles.grant_urls(grant)
    return DownloadLinkOut(
        id=grant.id,
        kind=grant.kind,
        label=grant.label,
        target_agent=grant.target_agent,
        bundle_url=bundle_url,
        manifest_url=manifest_url,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        download_count=grant.download_count,
        last_used_at=grant.last_used_at,
        created_at=grant.created_at,
    )


@router.post("/versions/{version_id}/download-links", response_model=DownloadLinkOut, status_code=201)
async def create_download_link(version_id: str, body: DownloadLinkIn, session: SessionDep, user: CurrentUser):
    """Create an online address from which an agent can fetch INSTALL.md, install.json and every artifact."""
    version, skill = await _version(session, user, version_id, ProjectRole.viewer)
    if version.state in ("discarded", "rejected"):
        raise Conflict("version_not_installable", state=version.state)
    if body.target_agent:
        try:
            get_adapter(body.target_agent)
        except KeyError:
            raise ValidationFailed("unknown_target") from None
    grant, _token = await bundles.create_grant(
        session,
        skill=skill,
        version=version,
        kind="version",
        created_by=user.id,
        expires_in_days=body.expires_in_days,
        label=body.label,
        target_agent=body.target_agent,
    )
    await record_audit(
        session,
        "download_link.create",
        actor_user_id=user.id,
        subject_type="skill_version",
        subject_id=version.id,
        after={"grant_id": grant.id, "expires_at": grant.expires_at.isoformat() if grant.expires_at else None},
    )
    await session.commit()
    await session.refresh(grant)
    return _link_out(grant)


@router.get("/versions/{version_id}/download-links", response_model=list[DownloadLinkOut])
async def list_download_links(version_id: str, session: SessionDep, user: CurrentUser):
    version, _ = await _version(session, user, version_id)
    res = await session.execute(
        select(DownloadGrant)
        .where(DownloadGrant.skill_version_id == version.id, DownloadGrant.kind == "version")
        .order_by(DownloadGrant.created_at.desc())
    )
    return [_link_out(g) for g in res.scalars()]


@router.delete("/download-links/{grant_id}", response_model=DownloadLinkOut)
async def revoke_download_link(grant_id: str, session: SessionDep, user: CurrentUser):
    grant = await session.get(DownloadGrant, grant_id)
    if grant is None:
        raise NotFound("link_not_found")
    await _version(session, user, grant.skill_version_id, ProjectRole.editor)
    if grant.revoked_at is None:
        grant.revoked_at = utcnow()
        await record_audit(
            session, "download_link.revoke", actor_user_id=user.id, subject_type="download_grant", subject_id=grant.id
        )
    await session.commit()
    await session.refresh(grant)
    return _link_out(grant)


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
