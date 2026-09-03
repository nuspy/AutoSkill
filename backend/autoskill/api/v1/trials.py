"""Trial sessions: requested from the web UI, installed and driven from the user's machine."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import select

from autoskill.api.v1.deps import AnyAuthUser, CurrentUser, SessionDep
from autoskill.api.v1.skills import get_skill_for
from autoskill.api.v1.versions import _install_context
from autoskill.core.errors import NotFound
from autoskill.models.project import ProjectRole
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion
from autoskill.models.trial import Checkpoint, Run, TrialSession
from autoskill.schemas.common import OkResponse
from autoskill.schemas.draft import InstallDoc, StepOut
from autoskill.schemas.trial import (
    CheckpointOut,
    RunOut,
    TrialCreate,
    TrialCreated,
    TrialDetail,
    TrialInstalled,
    TrialOut,
    TrialOutcomeIn,
)
from autoskill.services.packaging.store import load_package
from autoskill.services.targets import get_adapter
from autoskill.services.trials import service

router = APIRouter(prefix="/trials", tags=["trials"])


async def _get(session, user, trial_id: str) -> TrialSession:
    trial = await session.get(TrialSession, trial_id)
    if trial is None:
        raise NotFound("trial_not_found")
    if trial.user_id != user.id:
        await get_skill_for(session, trial.skill_id, user, ProjectRole.owner)  # owners/admins may inspect
    return trial


@router.post("", response_model=TrialCreated, status_code=201)
async def create(body: TrialCreate, session: SessionDep, user: AnyAuthUser):
    version = await session.get(SkillVersion, body.skill_version_id)
    if version is None:
        raise NotFound("version_not_found")
    skill = await get_skill_for(session, version.skill_id, user, ProjectRole.viewer)
    trial, token = await service.create_trial(
        session,
        user_id=user.id,
        version=version,
        skill=skill,
        target_agent=body.target_agent,
        purpose=body.purpose,
        mode=body.mode,
        device_id=body.device_id,
    )
    await session.commit()
    await session.refresh(trial)
    return TrialCreated(
        **TrialOut.model_validate(trial).model_dump(),
        session_token=token,
        cli_command=service.cli_command(trial, skill, version, token),
        package_url=service.package_url(trial),
    )


@router.get("", response_model=list[TrialOut])
async def list_mine(session: SessionDep, user: AnyAuthUser, skill_id: str | None = None, open_only: bool = False):
    stmt = select(TrialSession).where(TrialSession.user_id == user.id)
    if skill_id:
        stmt = stmt.where(TrialSession.skill_id == skill_id)
    if open_only:
        stmt = stmt.where(TrialSession.state.in_(service.OPEN_STATES))
    res = await session.execute(stmt.order_by(TrialSession.created_at.desc()))
    return res.scalars().all()


@router.get("/{trial_id}", response_model=TrialDetail)
async def detail(trial_id: str, session: SessionDep, user: AnyAuthUser):
    trial = await _get(session, user, trial_id)
    skill = await session.get(Skill, trial.skill_id)
    version = await session.get(SkillVersion, trial.skill_version_id)
    steps = await service.trial_steps(session, trial)
    runs = (
        (await session.execute(select(Run).where(Run.trial_session_id == trial.id).order_by(Run.started_at.desc())))
        .scalars()
        .all()
    )
    cps = (
        (
            await session.execute(
                select(Checkpoint).where(Checkpoint.trial_session_id == trial.id).order_by(Checkpoint.created_at)
            )
        )
        .scalars()
        .all()
    )
    pending = await service.pending_checkpoint(session, trial)
    await session.commit()
    return TrialDetail(
        trial=TrialOut.model_validate(trial),
        skill_name=skill.name if skill else "",
        skill_title=skill.title if skill else "",
        version=version.version if version else "",
        steps=[StepOut.model_validate(s).model_dump() for s in steps],
        runs=[RunOut.model_validate(r).model_dump() for r in runs],
        pending_checkpoint=CheckpointOut.model_validate(pending).model_dump() if pending else None,
        checkpoints=[CheckpointOut.model_validate(c).model_dump() for c in cps],
        package_url=service.package_url(trial),
    )


@router.post("/{trial_id}/installed", response_model=TrialOut)
async def installed(trial_id: str, body: TrialInstalled, session: SessionDep, user: AnyAuthUser):
    trial = await _get(session, user, trial_id)
    await service.mark_installed(session, trial, body.install_manifest, body.build)
    await session.commit()
    await session.refresh(trial)
    return trial


@router.post("/{trial_id}/suspend", response_model=TrialOut)
async def suspend(trial_id: str, session: SessionDep, user: AnyAuthUser):
    trial = await _get(session, user, trial_id)
    await service.suspend(session, trial)
    await session.commit()
    await session.refresh(trial)
    return trial


@router.post("/{trial_id}/resume", response_model=TrialOut)
async def resume(trial_id: str, session: SessionDep, user: AnyAuthUser):
    trial = await _get(session, user, trial_id)
    await service.resume(session, trial)
    await session.commit()
    await session.refresh(trial)
    return trial


@router.post("/{trial_id}/summary", response_model=TrialOut)
async def summary(trial_id: str, session: SessionDep, user: CurrentUser):
    trial = await _get(session, user, trial_id)
    if trial.state in ("installed", "testing", "suspended"):
        trial.state = "reviewing"
    await service.summarize(session, trial, language=user.locale)
    await session.commit()
    await session.refresh(trial)
    return trial


@router.post("/{trial_id}/outcome", response_model=TrialOut)
async def outcome(trial_id: str, body: TrialOutcomeIn, session: SessionDep, user: AnyAuthUser):
    trial = await _get(session, user, trial_id)
    await service.set_outcome(
        session, trial, outcome=body.outcome, keep_installed=body.keep_installed, note=body.note, user_id=user.id
    )
    await session.commit()
    await session.refresh(trial)
    return trial


@router.get("/{trial_id}/sync")
async def sync_state(trial_id: str, session: SessionDep, user: AnyAuthUser) -> dict:
    """Polled by the CLI: tells whether the installed build is stale and what state the trial is in."""
    trial = await _get(session, user, trial_id)
    version = await session.get(SkillVersion, trial.skill_version_id)
    installed_build = int((trial.install_manifest or {}).get("build") or 0)
    return {
        "state": trial.state,
        "current_build": version.build if version else trial.build,
        "installed_build": installed_build,
        "stale": bool(version and version.build != installed_build),
        "keep_installed": trial.keep_installed,
        "outcome": trial.outcome,
    }


@router.get("/{trial_id}/install/{target}", response_model=InstallDoc)
async def install_doc(trial_id: str, target: str, session: SessionDep, user: AnyAuthUser):
    trial = await _get(session, user, trial_id)
    skill = await session.get(Skill, trial.skill_id)
    version = await session.get(SkillVersion, trial.skill_version_id)
    ctx = await _install_context(session, skill, version, trial=True)
    ctx.zip_url = service.package_url(trial)
    return InstallDoc(target=target, markdown=get_adapter(target).render_install_md(ctx))


@router.get("/{trial_id}/package.zip")
async def package(trial_id: str, session: SessionDep, user: AnyAuthUser):
    trial = await _get(session, user, trial_id)
    skill = await session.get(Skill, trial.skill_id)
    version = await session.get(SkillVersion, trial.skill_version_id)
    pkg = load_package(skill.name, version)
    fm = pkg.frontmatter()
    fm.setdefault("metadata", {})["autoskill_trial"] = trial.id
    fm["metadata"]["build"] = str(version.build)
    pkg.set_frontmatter(fm)
    ctx = await _install_context(session, skill, version, trial=True)
    ctx.zip_url = service.package_url(trial)
    extra = {f"INSTALL.{trial.target_agent}.md": get_adapter(trial.target_agent).render_install_md(ctx).encode()}
    import json

    extra["autoskill.json"] = json.dumps(
        {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "version_id": version.id,
            "version": version.version,
            "build": version.build,
            "trial_session_id": trial.id,
            "mcp_servers": [m.name for m in ctx.mcp_servers],
            "server_url": ctx.server_url,
        },
        indent=2,
    ).encode()
    return Response(
        content=pkg.to_zip(extra),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill.name}-{version.version}-trial.zip"'},
    )


@router.delete("/{trial_id}", response_model=OkResponse)
async def abandon(trial_id: str, session: SessionDep, user: AnyAuthUser):
    trial = await _get(session, user, trial_id)
    if trial.state in service.OPEN_STATES:
        await service.set_outcome(session, trial, outcome="abandoned", keep_installed=False, note=None, user_id=user.id)
        await session.commit()
    return OkResponse()
