"""Interview session lifecycle: create, answer, confirm, suspend/resume, run via jobs."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.jobs import get_job_runner
from autoskill.models.interview import InterviewMessage, InterviewSession, KnowledgeDoc
from autoskill.models.procedure import Procedure
from autoskill.models.skill import Skill
from autoskill.services.procedures import engine

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def skill_name_from_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:64].strip("-")
    return slug or "skill"


async def unique_skill_name(session: AsyncSession, project_id: str, base: str) -> str:
    name, n = base, 1
    while (await session.execute(select(Skill.id).where(Skill.project_id == project_id, Skill.name == name))).first():
        n += 1
        suffix = f"-{n}"
        name = base[: 64 - len(suffix)] + suffix
    return name


async def start_interview(
    session: AsyncSession,
    *,
    project_id: str,
    user_id: str,
    title: str,
    description: str,
    language: str = "en",
    attachments: list[dict[str, Any]] | None = None,
    skill_id: str | None = None,
) -> InterviewSession:
    if skill_id:
        skill = await session.get(Skill, skill_id)
        if skill is None or skill.project_id != project_id:
            raise NotFound("skill_not_found")
        if skill.development_state == "suspended":
            raise Conflict("skill_suspended")
    else:
        name = await unique_skill_name(session, project_id, skill_name_from_title(title))
        skill = Skill(project_id=project_id, name=name, title=title.strip()[:200], created_by=user_id)
        session.add(skill)
        await session.flush()
    interview = InterviewSession(project_id=project_id, skill_id=skill.id, user_id=user_id, language=language)
    session.add(interview)
    await session.flush()
    procedure = await engine.create_procedure(
        session,
        "interview",
        subject_type="interview_session",
        subject_id=interview.id,
        project_id=project_id,
        context={"description": description, "attachments": attachments or []},
    )
    interview.procedure_id = procedure.id
    await session.commit()
    await get_job_runner().enqueue(
        "interview.run", {"session_id": interview.id}, project_id=project_id, user_id=user_id
    )
    return interview


async def _procedure(session: AsyncSession, interview: InterviewSession) -> Procedure:
    procedure = await session.get(Procedure, interview.procedure_id)
    if procedure is None:
        raise NotFound("procedure_not_found")
    return procedure


async def submit_answer(
    session: AsyncSession, interview: InterviewSession, text: str, attachments: list[dict[str, Any]] | None = None
) -> None:
    procedure = await _procedure(session, interview)
    if procedure.state != "waiting_human" or procedure.waiting_for != "answer":
        raise Conflict("not_awaiting_answer", state=interview.state)
    if not text.strip() and not attachments:
        raise ValidationFailed("empty_answer")
    await engine.resume(session, procedure, {"text": text.strip(), "attachments": attachments or []})
    interview.state = "exploring"
    await session.commit()
    await get_job_runner().enqueue(
        "interview.run", {"session_id": interview.id}, project_id=interview.project_id, user_id=interview.user_id
    )


async def submit_confirmation(
    session: AsyncSession, interview: InterviewSession, confirmed: bool, text: str | None = None
) -> None:
    procedure = await _procedure(session, interview)
    if procedure.state != "waiting_human" or procedure.waiting_for != "confirmation":
        raise Conflict("not_awaiting_confirmation", state=interview.state)
    if not confirmed and not (text or "").strip():
        raise ValidationFailed("correction_required")
    await engine.resume(session, procedure, {"confirmed": confirmed, "text": (text or "").strip()})
    interview.state = "exploring"
    await session.commit()
    await get_job_runner().enqueue(
        "interview.run", {"session_id": interview.id}, project_id=interview.project_id, user_id=interview.user_id
    )


async def abandon(session: AsyncSession, interview: InterviewSession) -> None:
    procedure = await _procedure(session, interview)
    if procedure.state in ("running", "waiting_human"):
        procedure.state = "cancelled"
    interview.state = "abandoned"
    await session.commit()


async def run_interview(session_id: str) -> None:
    """Job body: advance the procedure until it waits, completes or fails."""
    from autoskill.db.session import get_session_factory

    async with get_session_factory()() as session:
        interview = await session.get(InterviewSession, session_id)
        if interview is None:
            return
        procedure = await session.get(Procedure, interview.procedure_id)
        if procedure is None or procedure.state not in ("running",):
            return
        procedure = await engine.run(session, procedure)
        interview = await session.get(InterviewSession, session_id)
        if procedure.state == "failed" and interview is not None and interview.state not in ("failed", "complete"):
            interview.state = "failed"
            interview.error = (procedure.error or "")[:2000]
            await session.commit()
            from autoskill.services.procedures.defs.interview import _notify

            await _notify(interview, "interview.updated")


async def session_view(session: AsyncSession, interview: InterviewSession) -> dict[str, Any]:
    msgs = await session.execute(
        select(InterviewMessage).where(InterviewMessage.session_id == interview.id).order_by(InterviewMessage.ordinal)
    )
    knowledge = await session.get(KnowledgeDoc, interview.knowledge_id) if interview.knowledge_id else None
    procedure = await session.get(Procedure, interview.procedure_id) if interview.procedure_id else None
    return {
        "session": interview,
        "messages": list(msgs.scalars().all()),
        "knowledge": knowledge,
        "procedure_state": procedure.state if procedure else None,
        "waiting_for": procedure.waiting_for if procedure else None,
        "current_step": procedure.current_step_key if procedure else None,
        "supervisor": (procedure.context or {}).get("supervisor") if procedure else None,
    }
