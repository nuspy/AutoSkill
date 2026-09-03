"""Review queue: submit, assign, decide; publish/deprecate authorizations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from autoskill.core.events import emit, project_channel
from autoskill.core.permissions import is_reviewer
from autoskill.db.base import utcnow
from autoskill.models.project import ProjectMember
from autoskill.models.review import Authorization, ReviewDecision, ReviewRequest
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.models.trial import Run, TrialSession
from autoskill.models.user import User, UserRole
from autoskill.services.notifications import notify
from autoskill.services.settings import get_setting
from autoskill.services.versioning.state_machine import transition

DECISION_TO_STATE = {"approved": "approved", "changes_requested": "changes_requested", "rejected": "rejected"}


async def build_checklist(session: AsyncSession, version: SkillVersion) -> dict:
    steps = (
        (await session.execute(select(StepDefinition).where(StepDefinition.skill_version_id == version.id)))
        .scalars()
        .all()
    )
    trials = (
        (await session.execute(select(TrialSession).where(TrialSession.skill_version_id == version.id))).scalars().all()
    )
    runs = (await session.execute(select(Run).where(Run.skill_version_id == version.id))).scalars().all()
    golden = [r for r in runs if r.is_golden]
    return {
        "validation_ok": bool((version.validation_report or {}).get("ok")),
        "steps_total": len(steps),
        "steps_confirmed": sum(1 for s in steps if s.test_status in ("confirmed", "corrected")),
        "irreversible_steps": [s.key for s in steps if s.side_effects == "irreversible"],
        "trials": len(trials),
        "trials_accepted": sum(1 for t in trials if t.outcome == "accepted"),
        "runs": len(runs),
        "golden_runs": len(golden),
        "signature_present": bool(version.signature),
        "secrets_scan_ok": not any(
            i.get("code") == "secret_detected" for i in (version.validation_report or {}).get("issues", [])
        ),
    }


async def submit(session: AsyncSession, version: SkillVersion, actor: User, summary: str | None) -> ReviewRequest:
    existing = (
        await session.execute(
            select(ReviewRequest).where(
                ReviewRequest.skill_version_id == version.id, ReviewRequest.state.in_(("open", "in_review"))
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise Conflict("review_already_open")
    skill = await session.get(Skill, version.skill_id)
    await transition(session, version, "submitted_for_review", actor=actor, reason=summary)
    req = ReviewRequest(
        skill_version_id=version.id,
        skill_id=version.skill_id,
        project_id=skill.project_id,
        requested_by=actor.id,
        summary=summary,
        checklist=await build_checklist(session, version),
    )
    session.add(req)
    await session.flush()
    reviewers = (
        (
            await session.execute(
                select(User).where(User.role.in_((UserRole.admin, UserRole.reviewer)), User.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    for r in reviewers:
        if r.id != actor.id:
            await notify(
                session,
                r.id,
                "review_requested",
                f"Review requested: {skill.title} v{version.version}",
                subject_type="review_request",
                subject_id=req.id,
                payload={"skill_id": skill.id, "version_id": version.id},
            )
    await emit(project_channel(skill.project_id), "review.requested", {"request_id": req.id, "version_id": version.id})
    return req


async def withdraw(session: AsyncSession, req: ReviewRequest, actor: User) -> ReviewRequest:
    if req.state not in ("open", "in_review"):
        raise Conflict("review_not_open", state=req.state)
    version = await session.get(SkillVersion, req.skill_version_id)
    await transition(session, version, "tested", actor=actor, reason="withdrawn")
    req.state = "withdrawn"
    req.decided_at = utcnow()
    return req


async def assign(session: AsyncSession, req: ReviewRequest, reviewer: User) -> ReviewRequest:
    if req.state not in ("open", "in_review"):
        raise Conflict("review_not_open", state=req.state)
    req.assignee_id = reviewer.id
    req.state = "in_review"
    return req


async def decide(
    session: AsyncSession,
    req: ReviewRequest,
    reviewer: User,
    *,
    decision: str,
    comment: str | None,
    file_comments: list[dict],
) -> ReviewDecision:
    if decision not in DECISION_TO_STATE:
        raise ValidationFailed("unknown_decision", allowed=list(DECISION_TO_STATE))
    if req.state not in ("open", "in_review"):
        raise Conflict("review_not_open", state=req.state)
    if not is_reviewer(reviewer):
        raise Forbidden("reviewer_required")
    if req.requested_by == reviewer.id and not await get_setting(session, "allow_self_review"):
        raise Forbidden("self_review_not_allowed")
    row = ReviewDecision(
        review_request_id=req.id,
        reviewer_id=reviewer.id,
        decision=decision,
        comment=comment,
        file_comments=file_comments,
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    version = await session.get(SkillVersion, req.skill_version_id)
    await transition(
        session, version, DECISION_TO_STATE[decision], actor=reviewer, reason=comment, review_decision_id=row.id
    )
    req.state = "decided"
    req.decided_at = utcnow()
    skill = await session.get(Skill, version.skill_id)
    await notify(
        session,
        req.requested_by,
        "review_decided",
        f"Review {decision.replace('_', ' ')}: {skill.title} v{version.version}",
        body=comment,
        subject_type="skill_version",
        subject_id=version.id,
        payload={"decision": decision, "skill_id": skill.id},
    )
    await emit(
        project_channel(skill.project_id),
        "review.decided",
        {"request_id": req.id, "decision": decision, "version_id": version.id},
    )
    return row


async def authorize(
    session: AsyncSession,
    version: SkillVersion,
    actor: User,
    *,
    action: str,
    checklist: dict,
    comment: str | None,
    granted: bool = True,
) -> Authorization:
    if action not in ("publish", "deprecate"):
        raise ValidationFailed("unknown_action")
    skill = await session.get(Skill, version.skill_id)
    if skill is None:
        raise NotFound("skill_not_found")
    membership = (
        await session.execute(
            select(ProjectMember).where(ProjectMember.project_id == skill.project_id, ProjectMember.user_id == actor.id)
        )
    ).scalar_one_or_none()
    if actor.role != UserRole.admin and (membership is None or membership.role.value not in ("owner", "editor")):
        raise Forbidden("project_editor_required")
    required = (
        ("reviewed_diff", "trial_accepted", "install_docs_checked") if action == "publish" else ("installers_notified",)
    )
    missing = [k for k in required if not checklist.get(k)]
    if granted and missing:
        raise ValidationFailed("checklist_incomplete", missing=missing)
    auth = Authorization(
        project_id=skill.project_id,
        subject_type="skill_version",
        subject_id=version.id,
        action=action,
        requested_by=actor.id,
        decided_by=actor.id,
        decision="granted" if granted else "denied",
        comment=comment,
        checklist=checklist,
        created_at=utcnow(),
    )
    session.add(auth)
    await session.flush()
    if granted:
        await transition(
            session,
            version,
            "published" if action == "publish" else "deprecated",
            actor=actor,
            reason=comment,
            authorization_id=auth.id,
        )
        from autoskill.services.distribution.publish import on_published

        await on_published(session, skill, version, actor)
    return auth


async def queue(session: AsyncSession, *, state: str | None, assignee_id: str | None) -> list[ReviewRequest]:
    stmt = select(ReviewRequest)
    if state:
        stmt = stmt.where(ReviewRequest.state == state)
    else:
        stmt = stmt.where(ReviewRequest.state.in_(("open", "in_review")))
    if assignee_id:
        stmt = stmt.where(ReviewRequest.assignee_id == assignee_id)
    res = await session.execute(stmt.order_by(ReviewRequest.created_at))
    return list(res.scalars())


async def open_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count(ReviewRequest.id)).where(ReviewRequest.state.in_(("open", "in_review")))
            )
        ).scalar_one()
    )
