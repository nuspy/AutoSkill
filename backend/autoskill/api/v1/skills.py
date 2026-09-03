from fastapi import APIRouter
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.audit import record_audit
from autoskill.core.errors import NotFound
from autoskill.core.permissions import require_project_role
from autoskill.db.base import utcnow
from autoskill.models.interview import InterviewSession, KnowledgeDoc
from autoskill.models.project import ProjectRole
from autoskill.models.skill import Skill
from autoskill.schemas.common import OkResponse
from autoskill.schemas.interview import KnowledgeOut
from autoskill.schemas.skill import SkillOut, SkillUpdate, SuspendRequest

router = APIRouter(tags=["skills"])


async def get_skill_for(session, skill_id: str, user, minimum: ProjectRole) -> Skill:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        raise NotFound("skill_not_found")
    await require_project_role(session, skill.project_id, user, minimum)
    return skill


async def _out(session, skill: Skill) -> SkillOut:
    res = await session.execute(
        select(InterviewSession)
        .where(InterviewSession.skill_id == skill.id)
        .order_by(InterviewSession.created_at.desc())
        .limit(1)
    )
    latest = res.scalar_one_or_none()
    out = SkillOut.model_validate(skill)
    if latest:
        out.latest_interview_state = latest.state
        out.latest_interview_id = latest.id
    return out


@router.get("/projects/{project_id}/skills", response_model=list[SkillOut])
async def list_skills(project_id: str, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.viewer)
    res = await session.execute(
        select(Skill)
        .where(Skill.project_id == project_id, Skill.archived_at.is_(None))
        .order_by(Skill.updated_at.desc())
    )
    return [await _out(session, s) for s in res.scalars().all()]


@router.get("/skills/{skill_id}", response_model=SkillOut)
async def get_skill(skill_id: str, session: SessionDep, user: CurrentUser):
    return await _out(session, await get_skill_for(session, skill_id, user, ProjectRole.viewer))


@router.patch("/skills/{skill_id}", response_model=SkillOut)
async def update_skill(skill_id: str, body: SkillUpdate, session: SessionDep, user: CurrentUser):
    skill = await get_skill_for(session, skill_id, user, ProjectRole.editor)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(skill, key, value)
    await session.commit()
    return await _out(session, skill)


@router.post("/skills/{skill_id}/suspend", response_model=SkillOut)
async def suspend_skill(skill_id: str, body: SuspendRequest, session: SessionDep, user: CurrentUser):
    skill = await get_skill_for(session, skill_id, user, ProjectRole.editor)
    skill.development_state = "suspended"
    skill.suspended_at = utcnow()
    skill.suspend_note = body.note
    await record_audit(
        session,
        "skill.suspend",
        actor_user_id=user.id,
        project_id=skill.project_id,
        subject_type="skill",
        subject_id=skill.id,
    )
    await session.commit()
    return await _out(session, skill)


@router.post("/skills/{skill_id}/resume", response_model=SkillOut)
async def resume_skill(skill_id: str, session: SessionDep, user: CurrentUser):
    skill = await get_skill_for(session, skill_id, user, ProjectRole.editor)
    skill.development_state = "active"
    skill.suspended_at = None
    await record_audit(
        session,
        "skill.resume",
        actor_user_id=user.id,
        project_id=skill.project_id,
        subject_type="skill",
        subject_id=skill.id,
    )
    await session.commit()
    return await _out(session, skill)


@router.delete("/skills/{skill_id}", response_model=OkResponse)
async def archive_skill(skill_id: str, session: SessionDep, user: CurrentUser):
    skill = await get_skill_for(session, skill_id, user, ProjectRole.owner)
    skill.archived_at = utcnow()
    skill.development_state = "archived"
    await session.commit()
    return OkResponse()


@router.get("/skills/{skill_id}/knowledge", response_model=list[KnowledgeOut])
async def knowledge_history(skill_id: str, session: SessionDep, user: CurrentUser):
    await get_skill_for(session, skill_id, user, ProjectRole.viewer)
    res = await session.execute(
        select(KnowledgeDoc).where(KnowledgeDoc.skill_id == skill_id).order_by(KnowledgeDoc.revision.desc())
    )
    return res.scalars().all()
