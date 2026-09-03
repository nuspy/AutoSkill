"""Online-reachable downloads: install bundles by capability token, public hub bundles, autoskill-local wheels.

    /dl/autoskill-local/latest                  -> redirect to the newest wheel (public)
    /dl/autoskill-local/<file>.whl              -> wheel of the CLI + companion MCP (public)
    /dl/hub/<project>/<skill>/<version|latest>/<file>   -> bundle of a public skill (no token, needs public_hub)
    /dl/<token>/<file>                           -> bundle behind a download grant (trial or version link)

`<file>` is one of INSTALL.md, INSTALL.<target>.md, install.json, skill.zip, mcp/<name>.zip,
components/<slug>/<filename>. No login is required: the token (or the skill's public visibility) is the
authorization, and nothing here can write.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from autoskill.config import get_settings
from autoskill.core.errors import AppError, NotFound
from autoskill.core.ratelimit import limit
from autoskill.core.security import hash_token
from autoskill.db.base import utcnow
from autoskill.db.session import get_session_factory
from autoskill.models.hub import DownloadGrant
from autoskill.models.project import Project
from autoskill.models.skill import Skill
from autoskill.models.skill_version import LibraryComponent, SkillDependency, SkillVersion
from autoskill.models.trial import TrialSession
from autoskill.services.distribution import bundle as bundles
from autoskill.services.library.artifacts import load_artifact
from autoskill.services.settings import get_setting
from autoskill.services.targets import list_targets

router = APIRouter(prefix="/dl", tags=["downloads"])


class Gone(AppError):
    status_code = 410
    code = "link_expired"


# --- rate limit (shared across workers when Redis is configured) --------------------------


async def _rate_limit(key: str, session=None) -> None:
    per_minute = None
    if session is not None:
        per_minute = await get_setting(session, "download_rate_per_minute")
    await limit(f"dl:{key}", int(per_minute or 120))


# --- autoskill-local wheels ---------------------------------------------------------------


@router.get("/autoskill-local/latest")
async def companion_latest():
    wheel = bundles.companion_wheel()
    if wheel is None:
        raise NotFound("wheel_not_found", message="no autoskill-local wheel is published on this server")
    return RedirectResponse(f"{bundles.public_url()}/dl/autoskill-local/{wheel.name}", status_code=302)


@router.get("/autoskill-local/{filename}")
async def companion_wheel(filename: str, request: Request):
    await _rate_limit("ip:" + (request.client.host if request.client else "-"))
    if "/" in filename or not filename.endswith(".whl") or not filename.startswith("autoskill_local-"):
        raise NotFound("wheel_not_found")
    path = get_settings().dist_dir / filename
    if not path.is_file():
        raise NotFound("wheel_not_found")
    return Response(
        content=path.read_bytes(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- serving one bundle file --------------------------------------------------------------


async def _serve(session, skill: Skill, version: SkillVersion, bundle, path: str, trial: TrialSession | None):
    project = await session.get(Project, skill.project_id)
    slug = project.slug if project else ""
    targets = {t["id"] for t in list_targets()}
    if path in ("INSTALL.md", ""):
        target = bundle.default_target if bundle.default_target in targets else "hermes"
        return Response(bundles.render_install_md(bundle, target, slug), media_type="text/markdown; charset=utf-8")
    if path.startswith("INSTALL.") and path.endswith(".md"):
        target = path[len("INSTALL.") : -3]
        if target not in targets:
            raise NotFound("unknown_target", targets=sorted(targets))
        return Response(bundles.render_install_md(bundle, target, slug), media_type="text/markdown; charset=utf-8")
    if path in ("install.json", "autoskill.json"):
        return Response(bundles.bundle_json(bundle), media_type="application/json")
    if path == "skill.zip":
        data = await bundles.skill_zip(session, skill, version, bundle, trial=trial)
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{bundle.skill.download.filename}"'},
        )
    if path.startswith("mcp/") and path.endswith(".zip"):
        name = path[4:-4]
        mv = await bundles.generated_mcp(session, version)
        if mv is None or name != f"{skill.name}-tools":
            raise NotFound("mcp_not_found")
        return Response(
            content=bundles.mcp_zip(mv),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
        )
    if path.startswith("components/"):
        parts = path.split("/")
        if len(parts) != 3:
            raise NotFound("component_not_found")
        _, comp_slug, filename = parts
        declared = (
            await session.execute(
                select(SkillDependency.id).where(
                    SkillDependency.skill_version_id == version.id, SkillDependency.component_slug == comp_slug
                )
            )
        ).first()
        comp = (
            await session.execute(select(LibraryComponent).where(LibraryComponent.slug == comp_slug))
        ).scalar_one_or_none()
        if declared is None or comp is None or not comp.artifact or comp.artifact.get("filename") != filename:
            raise NotFound("component_not_found")
        record, data = load_artifact(comp)
        return Response(
            content=data,
            media_type=record.get("content_type", "application/octet-stream"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    raise NotFound("file_not_found")


# --- public hub bundles -------------------------------------------------------------------


@router.get("/hub/{project_slug}/{skill_name}/{version_label}/{path:path}")
async def hub_bundle(project_slug: str, skill_name: str, version_label: str, path: str, request: Request):
    async with get_session_factory()() as session:
        await _rate_limit("ip:" + (request.client.host if request.client else "-"), session)
        if not await get_setting(session, "public_hub"):
            raise NotFound("skill_not_found")
        project = (await session.execute(select(Project).where(Project.slug == project_slug))).scalar_one_or_none()
        if project is None:
            raise NotFound("skill_not_found")
        skill = (
            await session.execute(select(Skill).where(Skill.project_id == project.id, Skill.name == skill_name))
        ).scalar_one_or_none()
        if skill is None or skill.visibility != "public" or skill.archived_at is not None:
            raise NotFound("skill_not_found")
        if version_label == "latest":
            version = (
                await session.get(SkillVersion, skill.current_published_version_id)
                if skill.current_published_version_id
                else None
            )
        else:
            version = (
                await session.execute(
                    select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version == version_label)
                )
            ).scalar_one_or_none()
        if version is None or version.state not in ("published", "superseded"):
            raise NotFound("version_not_found")
        bundle = await bundles.build_bundle(
            session,
            skill=skill,
            version=version,
            base_url=bundles.hub_base_url(project.slug, skill.name, version.version),
            kind="hub",
        )
        return await _serve(session, skill, version, bundle, path, None)


# --- grant bundles ------------------------------------------------------------------------


async def resolve_grant(session, token: str) -> tuple[DownloadGrant, Skill, SkillVersion, TrialSession | None]:
    grant = (
        await session.execute(select(DownloadGrant).where(DownloadGrant.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if grant is None:
        raise NotFound("link_not_found")
    trial = await session.get(TrialSession, grant.trial_session_id) if grant.trial_session_id else None
    if not bundles.grant_active(grant, trial):
        raise Gone("link_expired", message="this download link is no longer valid")
    skill = await session.get(Skill, grant.skill_id)
    version = await session.get(SkillVersion, grant.skill_version_id)
    if skill is None or version is None or version.state == "discarded":
        raise Gone("link_expired")
    return grant, skill, version, trial


@router.get("/{token}/{path:path}")
async def grant_bundle(token: str, path: str, request: Request):
    async with get_session_factory()() as session:
        await _rate_limit("token:" + token[:16], session)
        grant, skill, version, trial = await resolve_grant(session, token)
        bundle = await bundles.build_bundle(
            session,
            skill=skill,
            version=version,
            base_url=bundles.grant_base_url(token),
            kind=grant.kind,  # type: ignore[arg-type]
            trial=trial,
            expires_at=grant.expires_at,
            default_target=grant.target_agent,
        )
        response = await _serve(session, skill, version, bundle, path, trial)
        grant.download_count += 1
        grant.last_used_at = utcnow()
        await session.commit()
        return response
