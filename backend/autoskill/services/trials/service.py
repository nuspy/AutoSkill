"""Trial session lifecycle: request, install, test, suspend/resume, summary and outcome."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.config import get_settings
from autoskill.core.crypto import decrypt, encrypt
from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.events import emit, project_channel, user_channel
from autoskill.core.security import generate_opaque_token, hash_token
from autoskill.db.base import utcnow
from autoskill.llm.budget import output_budget
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
        token_encrypted=encrypt(token),
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
    provider, provider_id = await get_provider("coach")
    res = await provider.chat(
        ChatRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=0.2,
            max_tokens=await output_budget(session),
            purpose="coach",
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


def stored_token(trial: TrialSession) -> str | None:
    """The trial's own token, when a recoverable copy was kept — never a new one.

    Re-issuing was the only way back to the install command, and it costs the previous token. That is
    the wrong price for merely looking: an agent may already be holding the old one, so recovering the
    instruction could break the very installation it describes. Trials created before the encrypted
    copy existed return None, and for those re-issuing remains the only route.
    """
    if not trial.token_encrypted:
        return None
    try:
        return decrypt(trial.token_encrypted)
    except Exception:
        # A changed secret_key makes every stored copy unreadable. That is a reason to fall back to
        # re-issuing, not to fail the page that was only trying to display a command.
        return None


async def reissue_token(session: AsyncSession, trial: TrialSession) -> str:
    """Mint a fresh session token for an open trial, replacing the one issued at creation.

    Only for trials whose token predates the encrypted copy, or whose copy can no longer be read:
    everything else should go through `stored_token`, which shows the real one and changes nothing.

    Replacing is not revealing. Re-issuing invalidates the previous token — which is right, and which
    the page must say before it happens.
    """
    if trial.state not in OPEN_STATES:
        raise Conflict("trial_closed", state=trial.state)
    token = generate_opaque_token(24)
    trial.token_hash = hash_token(token)
    trial.token_encrypted = encrypt(token)
    await session.commit()
    return token


CLOSED_STATES = ("decided", "removed", "abandoned")


async def purge_trial(session: AsyncSession, trial: TrialSession) -> dict[str, int]:
    """Delete a closed trial and everything hanging off it, for good.

    Closing a trial ends it but keeps the row, which is right while there is anything to learn from
    it. Once there is not, the list goes on showing attempts nobody will look at again, and the only
    way to stop seeing one was to stop looking at the list.

    Rows are removed explicitly rather than left to the database. The `ondelete="CASCADE"` on the
    tables hanging off `runs` is real but inert here: SQLite only honours foreign keys when
    `PRAGMA foreign_keys=ON`, which this application never sets, so relying on it would leave orphans
    on the deployment we actually run and delete them on another. Explicit is also the only version
    whose order can be read.

    The download grant goes with it: it is the capability that lets anyone holding the URL fetch the
    bundle without logging in, and outliving the trial it belonged to is exactly what it must not do.

    The skill package itself is untouched — it belongs to the version, not to this attempt at it, and
    other trials and installations share the same stored content.
    """
    if trial.state not in CLOSED_STATES:
        raise Conflict(
            "trial_not_closed",
            state=trial.state,
            message="Finish or remove the trial before deleting it.",
        )
    from sqlalchemy import delete

    from autoskill.models.hub import DownloadGrant
    from autoskill.models.trial import RunStep, StepDiscussion, TrialSnapshot

    run_ids = list(
        (await session.execute(select(Run.id).where(Run.trial_session_id == trial.id))).scalars().all()
    )
    removed: dict[str, int] = {}

    async def _delete(model, condition, label: str) -> None:
        res = await session.execute(delete(model).where(condition))
        removed[label] = res.rowcount or 0

    if run_ids:
        await _delete(RunStep, RunStep.run_id.in_(run_ids), "run_steps")
        await _delete(RunAnnotation, RunAnnotation.run_id.in_(run_ids), "run_annotations")
    await _delete(TrialSnapshot, TrialSnapshot.trial_session_id == trial.id, "snapshots")
    await _delete(StepDiscussion, StepDiscussion.trial_session_id == trial.id, "discussions")
    await _delete(Checkpoint, Checkpoint.trial_session_id == trial.id, "checkpoints")
    await _delete(DownloadGrant, DownloadGrant.trial_session_id == trial.id, "grants")
    await _delete(Run, Run.trial_session_id == trial.id, "runs")

    user_id, trial_id = trial.user_id, trial.id
    await session.delete(trial)
    await session.commit()
    await emit(user_channel(user_id), "trial.updated", {"trial_id": trial_id, "state": "deleted"})
    return removed


async def open_trial_for(session: AsyncSession, *, user_id: str, version_id: str) -> TrialSession | None:
    """This person's open trial of this version, if they have one.

    A trial belongs to one user, so its token does too: on a skill several people are trying at once
    each has their own, and the only correct answer to "show me the token" is the caller's.
    """
    res = await session.execute(
        select(TrialSession).where(
            TrialSession.user_id == user_id,
            TrialSession.skill_version_id == version_id,
            TrialSession.state.in_(OPEN_STATES),
        )
    )
    return res.scalars().first()


def stored_token_for(trial: TrialSession | None) -> str | None:
    return stored_token(trial) if trial is not None else None
