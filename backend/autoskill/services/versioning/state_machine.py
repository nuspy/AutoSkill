"""SkillVersion lifecycle: an explicit transition table with guards. Code decides, humans authorize.

draft -> testing -> tested -> submitted_for_review -> approved -> published -> superseded | deprecated
                                    |-> changes_requested -> submitted_for_review
                                    |-> rejected
draft | testing | tested | changes_requested -> discarded
System actors (actor_user_id None) can never move a version beyond `tested`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.audit import record_audit
from autoskill.core.errors import Conflict, Forbidden
from autoskill.db.base import utcnow
from autoskill.models.review import VersionTransition
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.models.user import User

HUMAN_ONLY_TARGETS = {"submitted_for_review", "approved", "changes_requested", "rejected", "published", "deprecated"}


@dataclass
class TransitionContext:
    session: AsyncSession
    version: SkillVersion
    actor: User | None
    reason: str | None = None
    authorization_id: str | None = None
    review_decision_id: str | None = None


Guard = Callable[[TransitionContext], Awaitable[None]]


async def _human(ctx: TransitionContext) -> None:
    if ctx.actor is None:
        raise Forbidden("human_required", message="This transition needs a person, not the system.")


async def _all_steps_confirmed(ctx: TransitionContext) -> None:
    res = await ctx.session.execute(select(StepDefinition).where(StepDefinition.skill_version_id == ctx.version.id))
    steps = list(res.scalars())
    untested = [s.key for s in steps if s.test_status not in ("confirmed", "corrected")]
    if untested:
        raise Conflict("steps_not_confirmed", steps=untested)


async def _validation_ok(ctx: TransitionContext) -> None:
    if not (ctx.version.validation_report or {}).get("ok", False):
        raise Conflict("validation_failed")


async def _review_decision_required(ctx: TransitionContext) -> None:
    await _human(ctx)
    if not ctx.review_decision_id:
        raise Conflict("review_decision_required")


async def _authorization_required(ctx: TransitionContext) -> None:
    await _human(ctx)
    if not ctx.authorization_id:
        raise Conflict("authorization_required")


async def _skill_not_suspended(ctx: TransitionContext) -> None:
    skill = await ctx.session.get(Skill, ctx.version.skill_id)
    if skill is not None and skill.development_state == "suspended" and ctx.version.state not in ("published",):
        raise Conflict("skill_suspended")


TRANSITIONS: dict[tuple[str, str], list[Guard]] = {
    ("draft", "testing"): [_validation_ok, _skill_not_suspended],
    ("testing", "tested"): [_all_steps_confirmed, _skill_not_suspended],
    ("tested", "submitted_for_review"): [_human, _validation_ok, _skill_not_suspended],
    ("changes_requested", "submitted_for_review"): [_human, _validation_ok, _skill_not_suspended],
    ("submitted_for_review", "tested"): [_human],  # withdraw
    ("submitted_for_review", "approved"): [_review_decision_required],
    ("submitted_for_review", "changes_requested"): [_review_decision_required],
    ("submitted_for_review", "rejected"): [_review_decision_required],
    ("approved", "published"): [_authorization_required],
    ("published", "superseded"): [],
    ("published", "deprecated"): [_authorization_required],
    ("changes_requested", "testing"): [_skill_not_suspended],  # go back to trials after edits
    ("tested", "testing"): [_skill_not_suspended],  # re-test
    ("draft", "discarded"): [],
    ("testing", "discarded"): [],
    ("tested", "discarded"): [],
    ("changes_requested", "discarded"): [],
}


def allowed_targets(state: str) -> list[str]:
    return sorted(to for (frm, to) in TRANSITIONS if frm == state)


async def transition(
    session: AsyncSession,
    version: SkillVersion,
    to_state: str,
    *,
    actor: User | None,
    reason: str | None = None,
    authorization_id: str | None = None,
    review_decision_id: str | None = None,
) -> SkillVersion:
    key = (version.state, to_state)
    if key not in TRANSITIONS:
        raise Conflict(
            "illegal_transition", from_state=version.state, to_state=to_state, allowed=allowed_targets(version.state)
        )
    if to_state in HUMAN_ONLY_TARGETS and actor is None:
        raise Forbidden("human_required")
    ctx = TransitionContext(
        session=session,
        version=version,
        actor=actor,
        reason=reason,
        authorization_id=authorization_id,
        review_decision_id=review_decision_id,
    )
    for guard in TRANSITIONS[key]:
        await guard(ctx)
    from_state = version.state
    version.state = to_state
    version.state_changed_at = utcnow()
    if to_state in ("published", "superseded", "deprecated", "discarded", "rejected"):
        version.is_current_draft = False
    session.add(
        VersionTransition(
            skill_version_id=version.id,
            from_state=from_state,
            to_state=to_state,
            actor_user_id=actor.id if actor else None,
            reason=reason,
            authorization_id=authorization_id,
            review_decision_id=review_decision_id,
            created_at=utcnow(),
        )
    )
    skill = await session.get(Skill, version.skill_id)
    await record_audit(
        session,
        f"version.{to_state}",
        actor_user_id=actor.id if actor else None,
        project_id=skill.project_id if skill else None,
        subject_type="skill_version",
        subject_id=version.id,
        before={"state": from_state},
        after={"state": to_state},
    )
    if to_state == "published" and skill is not None:
        # supersede the previously published version and point the skill at the new one
        if skill.current_published_version_id and skill.current_published_version_id != version.id:
            old = await session.get(SkillVersion, skill.current_published_version_id)
            if old is not None and old.state == "published":
                await transition(session, old, "superseded", actor=None, reason=f"superseded by {version.version}")
        skill.current_published_version_id = version.id
    if to_state == "deprecated" and skill is not None and skill.current_published_version_id == version.id:
        skill.current_published_version_id = None
    return version
