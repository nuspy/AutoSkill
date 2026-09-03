"""Trial session lifecycle: request, install, test, suspend/resume, summary and outcome."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.config import get_settings
from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.events import emit, project_channel, user_channel
from autoskill.core.security import generate_opaque_token, hash_token
from autoskill.db.base import utcnow
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.models.trial import Checkpoint, Run, RunAnnotation, TrialSession
from autoskill.services.targets import get_adapter

LANGUAGE_NAMES = {"en": "English", "it": "Italian", "hu": "Hungarian", "de": "German", "es": "Spanish", "fr": "French"}
OPEN_STATES = ("requested", "installing", "installed", "testing", "suspended", "reviewing")


def cli_command(
    trial: TrialSession, skill: Skill, version: SkillVersion, token: str, manifest_url: str | None = None
) -> str:
    if manifest_url:
        return f"autoskill trial install --from {manifest_url} --target {trial.target_agent} --token {token}"
    return (
        f"autoskill trial install {skill.name}@{version.version} "
        f"--target {trial.target_agent} --session {trial.id} --token {token}"
    )


def package_url(trial: TrialSession) -> str:
    return f"{get_settings().public_url}/api/v1/trials/{trial.id}/package.zip"


async def bundle_urls(session: AsyncSession, trial: TrialSession) -> tuple[str | None, str | None]:
    """(INSTALL.md url, install.json url) of the trial's download grant, reachable without login."""
    from autoskill.services.distribution import bundle as bundles

    grant = await bundles.trial_grant(session, trial)
    if grant is None:
        return None, None
    return bundles.grant_urls(grant)


async def create_trial(
    session: AsyncSession,
    *,
    user_id: str,
    version: SkillVersion,
    skill: Skill,
    target_agent: str,
    purpose: str,
    mode: str,
    device_id: str | None,
    auto_confirm: bool = True,
) -> tuple[TrialSession, str]:
    try:
        get_adapter(target_agent)
    except KeyError:
        raise ValidationFailed("unknown_target") from None
    if version.state in ("discarded", "rejected", "deprecated"):
        raise Conflict("version_not_testable", state=version.state)
    if skill.development_state == "suspended" and purpose == "develop":
        raise Conflict("skill_suspended")
    res = await session.execute(
        select(TrialSession).where(
            TrialSession.user_id == user_id,
            TrialSession.skill_version_id == version.id,
            TrialSession.state.in_(OPEN_STATES),
        )
    )
    if res.scalars().first() is not None:
        raise Conflict(
            "trial_already_open", message="You already have an open trial for this version; resume or close it first."
        )
    token = generate_opaque_token(24)
    trial = TrialSession(
        user_id=user_id,
        project_id=skill.project_id,
        device_id=device_id,
        skill_id=skill.id,
        skill_version_id=version.id,
        purpose=purpose,
        target_agent=target_agent,
        mode=mode,
        auto_confirm=auto_confirm,
        state="requested",
        token_hash=hash_token(token),
        build=version.build,
    )
    session.add(trial)
    await session.flush()
    from autoskill.services.distribution import bundle as bundles

    await bundles.create_grant(session, skill=skill, version=version, kind="trial", created_by=user_id, trial=trial)
    if version.state == "draft":
        from autoskill.services.versioning.state_machine import transition

        await transition(session, version, "testing", actor=None, reason="trial requested")
    await emit(user_channel(user_id), "trial.updated", {"trial_id": trial.id, "state": trial.state})
    return trial, token


async def trial_from_token(session: AsyncSession, token: str) -> TrialSession:
    res = await session.execute(select(TrialSession).where(TrialSession.token_hash == hash_token(token)))
    trial = res.scalar_one_or_none()
    if trial is None or trial.state not in OPEN_STATES:
        raise NotFound("trial_not_found")
    return trial


async def mark_installed(session: AsyncSession, trial: TrialSession, manifest: dict, build: int | None) -> TrialSession:
    if trial.state not in ("requested", "installing", "installed", "testing", "suspended"):
        raise Conflict("trial_not_open", state=trial.state)
    trial.install_manifest = manifest
    if build is not None:
        trial.build = build
    if trial.state in ("requested", "installing"):
        trial.state = "installed"
    await emit(user_channel(trial.user_id), "trial.updated", {"trial_id": trial.id, "state": trial.state})
    return trial


async def suspend(session: AsyncSession, trial: TrialSession) -> TrialSession:
    if trial.state not in ("installed", "testing"):
        raise Conflict("trial_not_suspendable", state=trial.state)
    trial.state = "suspended"
    trial.suspended_at = utcnow()
    await emit(user_channel(trial.user_id), "trial.updated", {"trial_id": trial.id, "state": trial.state})
    return trial


async def resume(session: AsyncSession, trial: TrialSession) -> TrialSession:
    if trial.state != "suspended":
        raise Conflict("trial_not_suspended", state=trial.state)
    trial.state = "testing" if trial.started_at else "installed"
    trial.suspended_at = None
    await emit(user_channel(trial.user_id), "trial.updated", {"trial_id": trial.id, "state": trial.state})
    return trial


async def trial_steps(session: AsyncSession, trial: TrialSession) -> list[StepDefinition]:
    res = await session.execute(
        select(StepDefinition)
        .where(StepDefinition.skill_version_id == trial.skill_version_id)
        .order_by(StepDefinition.ordinal)
    )
    return list(res.scalars().all())


async def summarize(session: AsyncSession, trial: TrialSession, language: str = "en") -> str:
    from autoskill.llm.provider import ChatMessage, ChatRequest
    from autoskill.llm.registry import get_provider
    from autoskill.llm.usage import record_usage
    from autoskill.prompts import render

    skill = await session.get(Skill, trial.skill_id)
    version = await session.get(SkillVersion, trial.skill_version_id)
    steps = await trial_steps(session, trial)
    runs = (
        (await session.execute(select(Run).where(Run.trial_session_id == trial.id).order_by(Run.started_at.desc())))
        .scalars()
        .all()
    )
    issues = (
        (
            await session.execute(
                select(RunAnnotation).where(
                    RunAnnotation.run_id.in_([r.id for r in runs]) if runs else False, RunAnnotation.kind == "issue"
                )
            )
        )
        .scalars()
        .all()
        if runs
        else []
    )
    prompt = render(
        "trial_summary",
        language_name=LANGUAGE_NAMES.get(language, "English"),
        skill_title=skill.title if skill else "",
        version=version.version if version else "",
        steps=steps,
        corrections=trial.corrections,
        run_status=runs[0].status if runs else "no run",
        issues=len(issues),
    )
    provider, provider_id = await get_provider(session, trial.project_id, "coach")
    res = await provider.chat(
        ChatRequest(
            messages=[ChatMessage(role="user", content=prompt)], temperature=0.2, max_tokens=800, purpose="coach"
        )
    )
    await record_usage(session, trial.project_id, provider_id, res.usage)
    trial.summary = res.text.strip()
    return trial.summary


async def set_outcome(
    session: AsyncSession,
    trial: TrialSession,
    *,
    outcome: str,
    keep_installed: bool,
    note: str | None,
    user_id: str,
) -> TrialSession:
    if trial.state not in ("installed", "testing", "suspended", "reviewing"):
        raise Conflict("trial_not_open", state=trial.state)
    version = await session.get(SkillVersion, trial.skill_version_id)
    steps = await trial_steps(session, trial)
    trial.outcome = outcome
    trial.keep_installed = keep_installed
    trial.ended_at = utcnow()
    if note:
        trial.summary = ((trial.summary or "").rstrip() + "\n\n" + note).strip()
    if outcome == "accepted":
        untested = [s.key for s in steps if s.test_status not in ("confirmed", "corrected")]
        if untested and trial.purpose == "develop":
            raise ValidationFailed("steps_not_confirmed", steps=untested)
        trial.state = "decided"
        if version is not None and version.state in ("draft", "testing") and trial.purpose in ("develop", "retest"):
            from autoskill.services.versioning.state_machine import transition

            for s in steps:
                if s.test_status == "corrected":
                    s.test_status = "confirmed"
            if version.state == "draft":
                await transition(session, version, "testing", actor=None, reason="trial accepted")
            await transition(session, version, "tested", actor=None, reason="trial accepted")
        # mark the latest run as human-approved
        run = (
            await session.execute(
                select(Run).where(Run.trial_session_id == trial.id).order_by(Run.started_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if run is not None and run.human_feedback is None:
            run.human_feedback = "corrected" if trial.corrections else "ok"
    elif outcome == "changes_requested":
        trial.state = "decided"
        trial.keep_installed = keep_installed
        if version is not None:
            from autoskill.core.jobs import get_job_runner

            corrections = "\n".join(f"- step {c['step_key']}: {c['text']}" for c in trial.corrections) or (note or "")
            await get_job_runner().enqueue(
                "draft.generate",
                {
                    "skill_id": trial.skill_id,
                    "user_id": user_id,
                    "mode": "patch",
                    "base_version_id": version.id,
                    "origin": "trial_corrections",
                    "instructions": "Apply these corrections gathered during the trial:\n" + corrections,
                },
                project_id=trial.project_id,
                user_id=user_id,
            )
    elif outcome in ("removed", "major_rework", "abandoned"):
        trial.state = "removed" if outcome == "removed" else ("abandoned" if outcome == "abandoned" else "decided")
        trial.keep_installed = False
        if outcome == "major_rework" and version is not None and version.state == "testing":
            version.rationale = ((version.rationale or "") + "\nmajor rework requested after trial").strip()
    await emit(
        user_channel(trial.user_id), "trial.updated", {"trial_id": trial.id, "state": trial.state, "outcome": outcome}
    )
    await emit(
        project_channel(trial.project_id),
        "trial.updated",
        {"trial_id": trial.id, "state": trial.state, "outcome": outcome},
    )
    return trial


async def pending_checkpoint(session: AsyncSession, trial: TrialSession) -> Checkpoint | None:
    res = await session.execute(
        select(Checkpoint)
        .where(Checkpoint.trial_session_id == trial.id, Checkpoint.state == "pending")
        .order_by(Checkpoint.created_at.desc())
        .limit(1)
    )
    cp = res.scalar_one_or_none()
    if cp is not None and cp.expires_at < utcnow():
        cp.state = "expired"
        return None
    return cp


async def enqueue_memory_extraction(trial: TrialSession, *, user_id: str | None, language: str) -> None:
    """After the outcome is committed: turn corrections, discussions and summary into skill memory."""
    from autoskill.core.jobs import get_job_runner

    await get_job_runner().enqueue(
        "memory.extract",
        {"skill_id": trial.skill_id, "source": "trial_discussion", "source_ref": trial.id, "language": language},
        project_id=trial.project_id,
        user_id=user_id,
    )
