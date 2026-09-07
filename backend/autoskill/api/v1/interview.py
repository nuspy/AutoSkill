from typing import Annotated

from fastapi import APIRouter, Header, UploadFile
from sqlalchemy import select

from autoskill.api.v1.deps import AnyAuthUser, CurrentUser, InterviewCallerDep, SessionDep
from autoskill.core.errors import NotFound, ValidationFailed
from autoskill.core.permissions import require_project_role
from autoskill.models.interview import InterviewSession
from autoskill.config import get_settings
from autoskill.models.project import Project, ProjectMember, ProjectRole
from autoskill.schemas.common import OkResponse
from autoskill.db.session import get_session_factory
from autoskill.schemas.interview import (
    AgentInterviewStart,
    AgentInterviewStarted,
    AttachmentOut,
    HandoffOut,
    InterviewAnswer,
    InterviewConfirm,
    InterviewStart,
    KnowledgeOut,
    MessageOut,
    SessionDetail,
    SessionOut,
    StepOut,
    TurnReply,
)
from autoskill.services.interview import attachments, service
from autoskill.services.interview.waiting import wait_for_turn

router = APIRouter(tags=["interview"])


@router.post("/projects/{project_id}/interviews", response_model=SessionOut, status_code=201)
async def start(project_id: str, body: InterviewStart, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.editor)
    interview = await service.start_interview(
        session,
        project_id=project_id,
        user_id=user.id,
        title=body.title,
        description=body.description,
        language=body.language,
        attachments=body.attachments,
        skill_id=body.skill_id,
    )
    return interview


@router.post("/projects/{project_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(project_id: str, file: UploadFile, session: SessionDep, user: CurrentUser):
    """Store a file and describe it. The descriptor travels with the interview start or answer."""
    await require_project_role(session, project_id, user, ProjectRole.editor)
    data = await file.read()
    if not data:
        raise ValidationFailed("empty_file")
    if len(data) > attachments.MAX_BYTES:
        raise ValidationFailed("file_too_large", limit=attachments.MAX_BYTES)
    return attachments.store_attachment(file.filename or "file", file.content_type or "", data)


@router.get("/projects/{project_id}/interviews", response_model=list[SessionOut])
async def list_sessions(project_id: str, session: SessionDep, user: CurrentUser, skill_id: str | None = None):
    await require_project_role(session, project_id, user, ProjectRole.viewer)
    stmt = select(InterviewSession).where(InterviewSession.project_id == project_id)
    if skill_id:
        stmt = stmt.where(InterviewSession.skill_id == skill_id)
    res = await session.execute(stmt.order_by(InterviewSession.created_at.desc()))
    return res.scalars().all()


# --- the executor: an agent attached to this session ---------------------------------------
#
# The application keeps leading and the person keeps answering in the browser. These endpoints let
# an agent take the turns addressed to it — looking at the machine and reporting back — so the
# interview can stop asking people to recall paths, columns and versions.


@router.post("/interviews/{session_id}/handoff", response_model=HandoffOut)
async def handoff(session_id: str, session: SessionDep, user: CurrentUser):
    """Mint the token the person pastes into their agent. Shown once, revoked by re-issuing."""
    interview = await _get(session, user, session_id, ProjectRole.editor)
    token = await service.attach_agent(session, interview)
    return HandoffOut(
        session_token=token,
        instruction=(
            f"Assist AutoSkill interview {interview.id}: call the autoskill-companion tool "
            f"`assist_interview` with session_key='{token}', then keep calling `await_task` and "
            f"`report_task` until it reports done. AutoSkill leads the interview and the person "
            f"answers in their browser — only carry out what is asked of you and report what you find."
        ),
    )


@router.post("/interviews/agent", response_model=AgentInterviewStarted, status_code=201)
async def start_from_agent(body: AgentInterviewStart, session: SessionDep, user: AnyAuthUser):
    """Open a session from the agent, then send the person to the browser to carry on.

    The agent may hold a user API key from `autoskill login`, which is a delegation a person granted
    in a browser — so this accepts one, exactly as creating a trial does. What it does *not* grant is
    the right to decide anything: the interview happens in the browser as always.
    """
    project = await _project_for_agent(session, user, body.project)
    await require_project_role(session, project.id, user, ProjectRole.editor)
    interview = await service.start_interview(
        session,
        project_id=project.id,
        user_id=user.id,
        title=body.title or body.description.strip()[:60],
        description=body.description,
        language=body.language,
    )
    interview.origin = "agent"
    token = await service.attach_agent(session, interview)
    base = get_settings().public_url.rstrip("/")
    return AgentInterviewStarted(
        session_id=interview.id,
        skill_id=interview.skill_id,
        project=project.slug,
        session_token=token,
        url=f"{base}/p/{project.id}/skills/{interview.skill_id}/interview/{interview.id}",
    )


async def _project_for_agent(session, user, wanted: str | None) -> Project:
    """Resolve the project by id or slug; with none named, only an unambiguous single one will do."""
    stmt = select(Project).join(ProjectMember, ProjectMember.project_id == Project.id).where(
        ProjectMember.user_id == user.id
    )
    projects = list((await session.execute(stmt)).scalars().all())
    if wanted:
        for p in projects:
            if wanted in (p.id, p.slug):
                return p
        raise NotFound("project_not_found")
    if len(projects) == 1:
        return projects[0]
    # the agent has no interface to choose with: hand back the options so it can ask the person
    raise ValidationFailed("choose_project", projects=[{"slug": p.slug, "name": p.name} for p in projects])


# no interview id in these paths: the session token already says which one, and a mismatch between
# the two would only be another thing to get wrong


@router.get("/interviews/turn")
async def current_turn(
    interview: InterviewCallerDep,
    session: SessionDep,
    wait: int = 0,
    x_autoskill_client: Annotated[str | None, Header()] = None,
) -> dict:
    """What the application is asking for right now. Held open up to 50 s, then ask again."""
    # note the visit and commit before waiting: the request's session must not hold the writer lock
    # while we poll, or the interview job cannot make progress
    await service.agent_seen(session, interview)
    # an executor too old to be trusted with the newer tools is sent to update first; the pending
    # turn is untouched, so it resumes on the very next call
    stale = service.update_turn(x_autoskill_client)
    if stale is not None:
        return stale
    return await wait_for_turn(get_session_factory(), interview.id, wait)


@router.post("/interviews/turn")
async def reply_turn(body: TurnReply, interview: InterviewCallerDep, session: SessionDep) -> dict:
    """Report the outcome of what was asked. Same shape a person's answer takes."""
    return await service.submit_turn(
        session, interview, text=body.text, attachments=body.attachments, turn_id=body.turn_id, via="agent"
    )


@router.post("/interviews/turn/attachments", response_model=AttachmentOut, status_code=201)
async def upload_turn_attachment(file: UploadFile, interview: InterviewCallerDep):
    """A file the agent found; the server summarises it exactly as it does for a browser upload."""
    data = await file.read()
    if not data:
        raise ValidationFailed("empty_file")
    if len(data) > attachments.MAX_BYTES:
        raise ValidationFailed("file_too_large", limit=attachments.MAX_BYTES)
    return attachments.store_attachment(file.filename or "file", file.content_type or "", data)


async def _get(session, user, session_id: str, minimum: ProjectRole = ProjectRole.viewer) -> InterviewSession:
    interview = await session.get(InterviewSession, session_id)
    if interview is None:
        raise NotFound("interview_not_found")
    await require_project_role(session, interview.project_id, user, minimum)
    return interview


@router.get("/interviews/{session_id}", response_model=SessionDetail)
async def detail(session_id: str, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id)
    view = await service.session_view(session, interview)
    return SessionDetail(
        session=SessionOut.model_validate(view["session"]).model_copy(
            update={
                "agent_attached": interview.agent_token_hash is not None,
                "agent_live": service.has_live_agent(interview),
            }
        ),
        messages=[MessageOut.model_validate(m) for m in view["messages"]],
        knowledge=KnowledgeOut.model_validate(view["knowledge"]) if view["knowledge"] else None,
        procedure_state=view["procedure_state"],
        waiting_for=view["waiting_for"],
        current_step=view["current_step"],
        supervisor=view["supervisor"],
        replay=view["replay"],
    )


@router.get("/interviews/{session_id}/steps", response_model=list[StepOut])
async def steps(session_id: str, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id)
    rows = await service.step_history(session, interview)
    return [
        StepOut.model_validate(row).model_copy(update={"replayable": row.checkpoint is not None}) for row in rows
    ]


@router.post("/interviews/{session_id}/steps/{ordinal}/replay", response_model=OkResponse)
async def replay(session_id: str, ordinal: int, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id, ProjectRole.editor)
    await service.replay_step(session, interview, ordinal)
    return OkResponse()


@router.post("/interviews/{session_id}/replay/accept", response_model=OkResponse)
async def accept_replay(session_id: str, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id, ProjectRole.editor)
    await service.accept_replay(session, interview)
    return OkResponse()


@router.post("/interviews/{session_id}/replay/discard", response_model=OkResponse)
async def discard_replay(session_id: str, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id, ProjectRole.editor)
    await service.discard_replay(session, interview)
    return OkResponse()


@router.post("/interviews/{session_id}/answer", response_model=OkResponse)
async def answer(session_id: str, body: InterviewAnswer, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id, ProjectRole.editor)
    await service.submit_answer(session, interview, body.text, body.attachments)
    return OkResponse()


@router.post("/interviews/{session_id}/confirm", response_model=OkResponse)
async def confirm(session_id: str, body: InterviewConfirm, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id, ProjectRole.editor)
    await service.submit_confirmation(session, interview, body.confirmed, body.text)
    return OkResponse()


@router.post("/interviews/{session_id}/retry", response_model=OkResponse)
async def retry(session_id: str, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id, ProjectRole.editor)
    await service.retry(session, interview)
    return OkResponse()


@router.post("/interviews/{session_id}/abandon", response_model=OkResponse)
async def abandon(session_id: str, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id, ProjectRole.editor)
    await service.abandon(session, interview)
    return OkResponse()
