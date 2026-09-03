"""Run and step ingestion shared by the telemetry API and the companion checkpoints."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.events import emit, project_channel
from autoskill.db.base import utcnow
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion
from autoskill.models.trial import Run, RunAnnotation, RunStep, TrialSession

RUN_STATUSES = ("running", "succeeded", "failed", "aborted", "needs_review")
STEP_STATUSES = ("proposed", "confirmed", "corrected", "skipped", "succeeded", "failed", "stopped")


async def resolve_skill(
    session: AsyncSession, *, project_id: str | None, skill_name: str | None, skill_id: str | None
) -> Skill:
    if skill_id:
        skill = await session.get(Skill, skill_id)
        if skill is None:
            raise NotFound("skill_not_found")
        return skill
    if not skill_name:
        raise ValidationFailed("skill_name_required")
    stmt = select(Skill).where(Skill.name == skill_name, Skill.archived_at.is_(None))
    if project_id:
        stmt = stmt.where(Skill.project_id == project_id)
    res = await session.execute(stmt.order_by(Skill.created_at.desc()))
    skill = res.scalars().first()
    if skill is None:
        raise NotFound("skill_not_found", skill_name=skill_name)
    return skill


async def resolve_version(
    session: AsyncSession, skill: Skill, version: str | None, version_id: str | None
) -> SkillVersion | None:
    if version_id:
        return await session.get(SkillVersion, version_id)
    if version:
        res = await session.execute(
            select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version == version)
        )
        return res.scalar_one_or_none()
    if skill.latest_version_id:
        return await session.get(SkillVersion, skill.latest_version_id)
    return None


async def start_run(
    session: AsyncSession,
    *,
    skill: Skill,
    version: SkillVersion | None,
    source: str,
    trial: TrialSession | None = None,
    agent_target: str | None = None,
    device_id: str | None = None,
    user_id: str | None = None,
    api_key_id: str | None = None,
    inputs_summary: str | None = None,
) -> Run:
    run = Run(
        project_id=skill.project_id,
        skill_id=skill.id,
        skill_version_id=version.id if version else None,
        skill_version=version.version if version else None,
        trial_session_id=trial.id if trial else None,
        source=source,
        agent_target=agent_target or (trial.target_agent if trial else None),
        device_id=device_id or (trial.device_id if trial else None),
        user_id=user_id or (trial.user_id if trial else None),
        api_key_id=api_key_id,
        status="running",
        inputs_summary=inputs_summary,
        started_at=utcnow(),
    )
    session.add(run)
    await session.flush()
    if trial is not None and trial.state in ("requested", "installing", "installed", "testing"):
        trial.state = "testing"
        trial.started_at = trial.started_at or utcnow()
    await emit(
        project_channel(skill.project_id), "run.started", {"run_id": run.id, "skill_id": skill.id, "source": source}
    )
    return run


async def next_step_ordinal(session: AsyncSession, run_id: str) -> int:
    res = await session.execute(select(func.coalesce(func.max(RunStep.ordinal), 0)).where(RunStep.run_id == run_id))
    return int(res.scalar_one()) + 1


async def log_step(
    session: AsyncSession, run: Run, data: dict[str, Any], idempotency_key: str | None = None
) -> RunStep:
    from autoskill.services.runs.redaction import cap_payload, redact

    if run.status != "running":
        raise Conflict("run_not_running", status=run.status)
    if idempotency_key:
        res = await session.execute(
            select(RunStep).where(RunStep.run_id == run.id, RunStep.idempotency_key == idempotency_key)
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            return existing
    status = data.get("status", "succeeded")
    if status not in STEP_STATUSES:
        raise ValidationFailed("unknown_step_status", status=status)
    step = RunStep(
        run_id=run.id,
        ordinal=await next_step_ordinal(session, run.id),
        step_key=data["step_key"][:64],
        title=(data.get("title") or "")[:200] or None,
        status=status,
        iteration=int(data.get("iteration") or 1),
        execution_mode=data.get("execution_mode"),
        proposed_action=cap_payload(redact(data.get("proposed_action"))),
        executed_action=cap_payload(redact(data.get("executed_action"))),
        inputs=cap_payload(redact(data.get("inputs"))),
        outputs=cap_payload(redact(data.get("outputs"))),
        error=cap_payload(redact(data.get("error"))),
        tool_name=(data.get("tool_name") or None),
        llm_usage=data.get("llm_usage"),
        idempotency_key=idempotency_key,
        started_at=data.get("started_at"),
        ended_at=data.get("ended_at"),
        duration_ms=data.get("duration_ms"),
        created_at=utcnow(),
    )
    session.add(step)
    await session.flush()
    await emit(
        project_channel(run.project_id), "run.step", {"run_id": run.id, "step_key": step.step_key, "status": status}
    )
    return step


async def end_run(
    session: AsyncSession, run: Run, *, status: str, summary: str | None, error: Any, llm_usage: dict | None
) -> Run:
    from autoskill.services.runs.redaction import redact

    if status not in ("succeeded", "failed", "aborted", "needs_review"):
        raise ValidationFailed("unknown_run_status", status=status)
    if run.status != "running":
        raise Conflict("run_not_running", status=run.status)
    run.status = status
    run.summary = redact(summary) if summary else None
    run.error = redact(error) if error else None
    if llm_usage:
        run.llm_usage = llm_usage
    run.ended_at = utcnow()
    run.duration_ms = int((run.ended_at - run.started_at).total_seconds() * 1000)
    await emit(project_channel(run.project_id), "run.ended", {"run_id": run.id, "status": status})
    return run


async def report_issue(
    session: AsyncSession,
    *,
    skill: Skill,
    run: Run | None,
    step_key: str | None,
    severity: str,
    description: str,
    evidence: Any,
    user_id: str | None,
) -> RunAnnotation:
    from autoskill.services.runs.redaction import cap_payload, redact

    if run is None:
        run = Run(
            project_id=skill.project_id,
            skill_id=skill.id,
            skill_version_id=skill.latest_version_id,
            source="production",
            status="needs_review",
            started_at=utcnow(),
            ended_at=utcnow(),
            duration_ms=0,
        )
        session.add(run)
        await session.flush()
    note = RunAnnotation(
        run_id=run.id,
        skill_id=skill.id,
        step_key=step_key,
        user_id=user_id,
        kind="issue",
        severity=severity,
        text=redact(description)[:4000],
        evidence=cap_payload(redact(evidence)) if evidence else None,
        created_at=utcnow(),
    )
    session.add(note)
    await session.flush()
    await emit(
        project_channel(skill.project_id), "run.issue", {"run_id": run.id, "skill_id": skill.id, "severity": severity}
    )
    return note
