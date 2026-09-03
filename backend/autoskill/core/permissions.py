"""Role helpers for global and project-level authorization."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Forbidden, NotFound
from autoskill.models.project import Project, ProjectMember, ProjectRole
from autoskill.models.user import User, UserRole

ROLE_ORDER = {ProjectRole.viewer: 0, ProjectRole.editor: 1, ProjectRole.owner: 2}


def is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def is_reviewer(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.reviewer)


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise Forbidden("admin_required")


def require_reviewer(user: User) -> None:
    if not is_reviewer(user):
        raise Forbidden("reviewer_required")


async def get_membership(
    session: AsyncSession, project_id: str, user: User
) -> ProjectMember | None:
    res = await session.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
        )
    )
    return res.scalar_one_or_none()


async def require_project_role(
    session: AsyncSession, project_id: str, user: User, minimum: ProjectRole
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound("project_not_found")
    if is_admin(user):
        return project
    membership = await get_membership(session, project_id, user)
    if membership is None or ROLE_ORDER[membership.role] < ROLE_ORDER[minimum]:
        raise Forbidden("insufficient_project_role")
    return project
