from fastapi import APIRouter
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.errors import NotFound
from autoskill.core.permissions import require_project_role
from autoskill.models.interview import InterviewSession
from autoskill.models.project import ProjectRole
from autoskill.schemas.common import OkResponse
from autoskill.schemas.interview import (
    InterviewAnswer,
    InterviewConfirm,
    InterviewStart,
    KnowledgeOut,
    MessageOut,
    SessionDetail,
    SessionOut,
)
from autoskill.services.interview import service

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


@router.get("/projects/{project_id}/interviews", response_model=list[SessionOut])
async def list_sessions(project_id: str, session: SessionDep, user: CurrentUser, skill_id: str | None = None):
    await require_project_role(session, project_id, user, ProjectRole.viewer)
    stmt = select(InterviewSession).where(InterviewSession.project_id == project_id)
    if skill_id:
        stmt = stmt.where(InterviewSession.skill_id == skill_id)
    res = await session.execute(stmt.order_by(InterviewSession.created_at.desc()))
    return res.scalars().all()


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
        session=SessionOut.model_validate(view["session"]),
        messages=[MessageOut.model_validate(m) for m in view["messages"]],
        knowledge=KnowledgeOut.model_validate(view["knowledge"]) if view["knowledge"] else None,
        procedure_state=view["procedure_state"],
        waiting_for=view["waiting_for"],
        current_step=view["current_step"],
        supervisor=view["supervisor"],
    )


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


@router.post("/interviews/{session_id}/abandon", response_model=OkResponse)
async def abandon(session_id: str, session: SessionDep, user: CurrentUser):
    interview = await _get(session, user, session_id, ProjectRole.editor)
    await service.abandon(session, interview)
    return OkResponse()
