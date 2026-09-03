import re

from fastapi import APIRouter
from sqlalchemy import func, select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.audit import record_audit
from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.permissions import get_membership, is_admin, require_project_role
from autoskill.models.project import Project, ProjectMember, ProjectRole
from autoskill.models.user import User
from autoskill.schemas.common import OkResponse
from autoskill.schemas.project import (
    MemberAdd,
    MemberOut,
    MemberUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "project"


async def _unique_slug(session, base: str) -> str:
    slug, n = base, 1
    while (await session.execute(select(Project.id).where(Project.slug == slug))).first():
        n += 1
        slug = f"{base}-{n}"
    return slug


async def _to_out(session, project: Project, user: User) -> ProjectOut:
    membership = await get_membership(session, project.id, user)
    count = (
        await session.execute(
            select(func.count(ProjectMember.id)).where(ProjectMember.project_id == project.id)
        )
    ).scalar_one()
    out = ProjectOut.model_validate(project)
    out.my_role = membership.role if membership else (ProjectRole.owner if is_admin(user) else None)
    out.member_count = int(count)
    return out


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: SessionDep, user: CurrentUser):
    if is_admin(user):
        res = await session.execute(select(Project).order_by(Project.created_at.desc()))
    else:
        res = await session.execute(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .order_by(Project.created_at.desc())
        )
    return [await _to_out(session, p, user) for p in res.scalars().all()]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, session: SessionDep, user: CurrentUser):
    project = Project(
        name=body.name,
        slug=await _unique_slug(session, slugify(body.name)),
        description=body.description,
        settings=body.settings,
        created_by=user.id,
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.owner))
    await record_audit(
        session, "project.create", actor_user_id=user.id, project_id=project.id,
        subject_type="project", subject_id=project.id, after={"name": project.name},
    )
    await session.commit()
    await session.refresh(project)
    return await _to_out(session, project, user)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, session: SessionDep, user: CurrentUser):
    project = await require_project_role(session, project_id, user, ProjectRole.viewer)
    return await _to_out(session, project, user)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, body: ProjectUpdate, session: SessionDep, user: CurrentUser):
    project = await require_project_role(session, project_id, user, ProjectRole.owner)
    before = {"name": project.name, "description": project.description}
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.settings is not None:
        project.settings = {**project.settings, **body.settings}
    await record_audit(
        session, "project.update", actor_user_id=user.id, project_id=project.id,
        subject_type="project", subject_id=project.id, before=before,
        after={"name": project.name, "description": project.description},
    )
    await session.commit()
    await session.refresh(project)
    return await _to_out(session, project, user)


@router.delete("/{project_id}", response_model=OkResponse)
async def delete_project(project_id: str, session: SessionDep, user: CurrentUser):
    project = await require_project_role(session, project_id, user, ProjectRole.owner)
    await record_audit(
        session, "project.delete", actor_user_id=user.id, project_id=project.id,
        subject_type="project", subject_id=project.id, before={"name": project.name},
    )
    await session.delete(project)
    await session.commit()
    return OkResponse()


# --- members ---------------------------------------------------------------------------


@router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(project_id: str, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.viewer)
    res = await session.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at)
    )
    return [
        MemberOut(
            id=m.id, user_id=u.id, email=u.email, display_name=u.display_name,
            role=m.role, created_at=m.created_at,
        )
        for m, u in res.all()
    ]


@router.post("/{project_id}/members", response_model=MemberOut, status_code=201)
async def add_member(project_id: str, body: MemberAdd, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.owner)
    res = await session.execute(select(User).where(User.email == body.email.lower()))
    target = res.scalar_one_or_none()
    if target is None:
        raise NotFound("user_not_found")
    if await get_membership(session, project_id, target) is not None:
        raise Conflict("already_member")
    member = ProjectMember(project_id=project_id, user_id=target.id, role=body.role)
    session.add(member)
    await record_audit(
        session, "project.member_add", actor_user_id=user.id, project_id=project_id,
        subject_type="user", subject_id=target.id, after={"role": body.role.value},
    )
    await session.commit()
    await session.refresh(member)
    return MemberOut(
        id=member.id, user_id=target.id, email=target.email, display_name=target.display_name,
        role=member.role, created_at=member.created_at,
    )


async def _owner_count(session, project_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count(ProjectMember.id)).where(
                    ProjectMember.project_id == project_id, ProjectMember.role == ProjectRole.owner
                )
            )
        ).scalar_one()
    )


@router.patch("/{project_id}/members/{member_id}", response_model=MemberOut)
async def update_member(
    project_id: str, member_id: str, body: MemberUpdate, session: SessionDep, user: CurrentUser
):
    await require_project_role(session, project_id, user, ProjectRole.owner)
    member = await session.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise NotFound("member_not_found")
    if member.role == ProjectRole.owner and body.role != ProjectRole.owner:
        if await _owner_count(session, project_id) <= 1:
            raise ValidationFailed("last_owner")
    member.role = body.role
    await session.commit()
    target = await session.get(User, member.user_id)
    return MemberOut(
        id=member.id, user_id=target.id, email=target.email, display_name=target.display_name,
        role=member.role, created_at=member.created_at,
    )


@router.delete("/{project_id}/members/{member_id}", response_model=OkResponse)
async def remove_member(project_id: str, member_id: str, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.owner)
    member = await session.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise NotFound("member_not_found")
    if member.role == ProjectRole.owner and await _owner_count(session, project_id) <= 1:
        raise ValidationFailed("last_owner")
    await session.delete(member)
    await session.commit()
    return OkResponse()
