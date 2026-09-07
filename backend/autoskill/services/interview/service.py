"""Interview session lifecycle: create, answer, confirm, suspend/resume, run via jobs."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.jobs import get_job_runner
from autoskill.core.security import generate_opaque_token, hash_token
from autoskill.db.base import utcnow
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


async def retry(session: AsyncSession, interview: InterviewSession) -> None:
    """Resume a procedure that stopped on a failure: the step that failed runs again from scratch.

    Meant for infrastructure errors (LLM unreachable, timeouts). The engine kept `current_step_key`
    and the context of the failed attempt, so nothing of the interview is lost.
    """
    procedure = await _procedure(session, interview)
    if procedure.state != "failed":
        raise Conflict("not_failed", state=interview.state)
    procedure.state = "running"
    procedure.error = None
    procedure.finished_at = None
    interview.state = "exploring"
    interview.error = None
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


# --- the executor: an agent attached to a session ------------------------------------------
#
# The application keeps leading and the person keeps answering in the browser. An attached agent
# only answers what can be observed on the machine, so the interview stops guessing at paths,
# columns and versions.

OPEN_FOR_AGENT = ("created", "intake", "exploring", "gating", "awaiting_answer", "awaiting_confirmation")


async def attach_agent(session: AsyncSession, interview: InterviewSession) -> str:
    """Mint the token an agent presents to join this session; the plain value is returned once."""
    if interview.state not in OPEN_FOR_AGENT:
        raise Conflict("interview_not_open", state=interview.state)
    token = generate_opaque_token()
    interview.agent_token_hash = hash_token(token)
    interview.agent_last_seen_at = None
    await session.commit()
    return token


async def interview_from_agent_token(session: AsyncSession, token: str) -> InterviewSession:
    res = await session.execute(
        select(InterviewSession).where(InterviewSession.agent_token_hash == hash_token(token))
    )
    interview = res.scalar_one_or_none()
    if interview is None or interview.state not in OPEN_FOR_AGENT:
        raise NotFound("interview_not_found")
    return interview


SEEN_RESOLUTION_S = 30


async def agent_seen(session: AsyncSession, interview: InterviewSession, target: str | None = None) -> None:
    """Note that the executor is alive — coarsely, because this competes with the interview job.

    The interface only asks "has the agent called recently"; writing the exact instant on every poll
    would buy nothing and cost a writer lock.
    """
    now = utcnow()
    fresh = interview.agent_last_seen_at is not None and (
        now - interview.agent_last_seen_at
    ).total_seconds() < SEEN_RESOLUTION_S
    if fresh and not (target and not interview.agent_target):
        return
    interview.agent_last_seen_at = now
    if target and not interview.agent_target:
        interview.agent_target = target
    await session.commit()


def has_live_agent(interview: InterviewSession, within_seconds: int = 120) -> bool:
    """True while an agent is polling. Beyond that the UI hands the turn back to the person."""
    if interview.agent_token_hash is None or interview.agent_last_seen_at is None:
        return False
    return (utcnow() - interview.agent_last_seen_at).total_seconds() <= within_seconds


def _version_key(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in (v or "0").split(".")[:3])


def update_turn(client_version: str | None) -> dict[str, Any] | None:
    """An older executor is asked to update itself before the interview goes on.

    The turn the interview is waiting on is not consumed: the agent updates, reloads its MCP
    servers and asks again, landing exactly where it left off.
    """
    from autoskill.services.distribution.bundle import companion_entry

    if not client_version:
        return None
    entry = companion_entry()
    if not entry.version or _version_key(client_version) >= _version_key(entry.version):
        return None
    return {
        "status": "update",
        "for": "agent",
        "reason": f"this machine runs autoskill-local {client_version}, the server publishes {entry.version}",
        "command": entry.install_command,
        "then": (
            "Run the command, then reload your MCP servers so the new tools are loaded, then call "
            "await_task again: the interview is waiting exactly where it was. If the update cannot "
            "be done, report it with report_task and the interview will carry on regardless."
        ),
    }


async def turn_view(session: AsyncSession, interview: InterviewSession) -> dict[str, Any]:
    """What is being asked right now, in one shape for the browser and for the agent.

    Keyed off `procedure.waiting_for`, never off `expects`: the confirmation step writes a raw dict
    with `expects: "confirmation"` that is not a QuestionSpec.
    """
    procedure = await _procedure(session, interview)
    turn_id = procedure.iteration
    if procedure.state == "running":
        return {"status": "working", "state": interview.state, "turn_id": turn_id}
    if procedure.state == "failed":
        return {"status": "failed", "turn_id": turn_id, "error": interview.error}
    if procedure.state in ("completed", "cancelled"):
        return {"status": "done", "turn_id": turn_id, "state": interview.state}
    question = interview.pending_question or {}
    if procedure.waiting_for == "confirmation":
        return {"status": "confirm", "turn_id": turn_id, "for": "person", "summary": question.get("question", "")}
    if question.get("audience") == "agent" and question.get("task"):
        task = question["task"]
        return {
            "status": "task",
            "turn_id": turn_id,
            "for": "agent",
            "mode": task.get("mode", "inspect"),
            "kind": task.get("kind", "other"),
            "instruction": question.get("question", ""),
            "why": question.get("why", ""),
            "targets": task.get("targets", []),
            "wants": task.get("wants", []),
            "may_upload": bool(task.get("may_upload")),
        }
    return {
        "status": "question",
        "turn_id": turn_id,
        "for": "person",
        "question": question.get("question", ""),
        "why": question.get("why", ""),
        "expects": question.get("expects", "text"),
        "options": question.get("options", []),
    }


async def submit_turn(
    session: AsyncSession,
    interview: InterviewSession,
    *,
    text: str,
    attachments: list[dict[str, Any]] | None = None,
    turn_id: int | None = None,
    via: str = "agent",
) -> dict[str, Any]:
    """Answer the current turn. A stale `turn_id` is refused with the turn that superseded it."""
    procedure = await _procedure(session, interview)
    if turn_id is not None and turn_id != procedure.iteration:
        raise Conflict(
            "turn_superseded",
            message="This turn was already answered; take the current one and continue.",
            current=await turn_view(session, interview),
        )
    if procedure.waiting_for == "confirmation":
        raise Conflict("not_awaiting_answer", state=interview.state)
    await submit_answer(session, interview, text, attachments)
    if via == "agent":
        # what the agent reported is evidence, not opinion: the ingest prompt is told so
        ctx = dict(procedure.context)
        ctx["_answered_by"] = "agent"
        procedure.context = ctx
        await session.commit()
    return {"status": "accepted", "turn_id": procedure.iteration}


async def step_history(session: AsyncSession, interview: InterviewSession) -> list[Any]:
    """Every step the procedure ran, including the ones a replay set aside."""
    procedure = await _procedure(session, interview)
    return await engine.steps(session, procedure)


async def replay_step(session: AsyncSession, interview: InterviewSession, ordinal: int) -> None:
    """Re-run a past step. The interview goes back to how it was just before that step ran."""
    procedure = await _procedure(session, interview)
    try:
        await engine.start_replay(session, procedure, ordinal)
    except LookupError as exc:
        raise NotFound("step_not_found") from exc
    except RuntimeError as exc:
        raise Conflict("replay_not_possible", detail=str(exc)) from exc
    interview.state = "exploring"
    interview.error = None
    await session.commit()
    await get_job_runner().enqueue(
        "interview.run", {"session_id": interview.id}, project_id=interview.project_id, user_id=interview.user_id
    )


async def accept_replay(session: AsyncSession, interview: InterviewSession) -> None:
    """Keep what the re-run produced; the steps it replaced become history."""
    procedure = await _procedure(session, interview)
    if procedure.state == "running":
        raise Conflict("replay_still_running", state=interview.state)
    try:
        await engine.accept_replay(session, procedure)
    except RuntimeError as exc:
        raise Conflict("no_replay", detail=str(exc)) from exc


async def discard_replay(session: AsyncSession, interview: InterviewSession) -> None:
    """Throw the re-run away and return to where the replay started."""
    procedure = await _procedure(session, interview)
    if procedure.state == "running":
        raise Conflict("replay_still_running", state=interview.state)
    try:
        # restores the session row too, through the procedure's restore hook
        await engine.discard_replay(session, procedure)
    except RuntimeError as exc:
        raise Conflict("no_replay", detail=str(exc)) from exc


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
    # messages left behind by a rewind stay in the table but are not part of the conversation
    visible = [m for m in msgs.scalars().all() if not (m.meta or {}).get("rewound")]
    return {
        "session": interview,
        "messages": visible,
        "knowledge": knowledge,
        "procedure_state": procedure.state if procedure else None,
        "waiting_for": procedure.waiting_for if procedure else None,
        "current_step": procedure.current_step_key if procedure else None,
        "supervisor": (procedure.context or {}).get("supervisor") if procedure else None,
        "replay": procedure.replay if procedure else None,
    }
