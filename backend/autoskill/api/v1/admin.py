from fastapi import APIRouter, Query
from sqlalchemy import func, select

from autoskill.api.v1.deps import AdminUser, SessionDep
from autoskill.core.audit import record_audit
from autoskill.core.errors import NotFound, ValidationFailed
from autoskill.models.audit import AuditLog
from autoskill.models.device import Device
from autoskill.models.job import Job
from autoskill.models.project import Project
from autoskill.models.user import User, UserRole
from autoskill.schemas.admin import AuditOut, JobOut, SettingsUpdate, StatsOut
from autoskill.schemas.common import Page
from autoskill.schemas.project import ProjectOut
from autoskill.schemas.user import AdminUserUpdate, UserOut
from autoskill.services.settings import DEFAULTS, get_all_settings, set_setting

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=StatsOut)
async def stats(session: SessionDep, _: AdminUser):
    async def count(stmt):
        return int((await session.execute(stmt)).scalar_one())

    return StatsOut(
        users=await count(select(func.count(User.id))),
        projects=await count(select(func.count(Project.id))),
        devices=await count(select(func.count(Device.id))),
        jobs_running=await count(select(func.count(Job.id)).where(Job.status == "running")),
    )


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    session: SessionDep, _: AdminUser, q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
):
    stmt = select(User)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where((func.lower(User.email).like(like)) | (func.lower(User.display_name).like(like)))
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    res = await session.execute(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset))
    return Page(items=[UserOut.model_validate(u) for u in res.scalars()], total=total)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: AdminUserUpdate, session: SessionDep, admin: AdminUser):
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("user_not_found")
    before = {"role": user.role.value, "is_active": user.is_active}
    if body.role is not None:
        if user.id == admin.id and body.role != UserRole.admin:
            raise ValidationFailed("cannot_demote_self")
        user.role = body.role
    if body.is_active is not None:
        if user.id == admin.id and not body.is_active:
            raise ValidationFailed("cannot_disable_self")
        user.is_active = body.is_active
    if body.display_name is not None:
        user.display_name = body.display_name
    await record_audit(
        session, "admin.user_update", actor_user_id=admin.id, subject_type="user",
        subject_id=user.id, before=before, after={"role": user.role.value, "is_active": user.is_active},
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/projects", response_model=list[ProjectOut])
async def list_all_projects(session: SessionDep, _: AdminUser):
    res = await session.execute(select(Project).order_by(Project.created_at.desc()))
    return [ProjectOut.model_validate(p) for p in res.scalars()]


@router.get("/settings")
async def read_settings(session: SessionDep, _: AdminUser) -> dict:
    return await get_all_settings(session)


@router.put("/settings")
async def write_settings(body: SettingsUpdate, session: SessionDep, admin: AdminUser) -> dict:
    unknown = set(body.values) - set(DEFAULTS)
    if unknown:
        raise ValidationFailed("unknown_settings", keys=sorted(unknown))
    before = await get_all_settings(session)
    for key, value in body.values.items():
        await set_setting(session, key, value)
    await record_audit(
        session, "admin.settings_update", actor_user_id=admin.id,
        before={k: before.get(k) for k in body.values}, after=body.values,
    )
    await session.commit()
    return await get_all_settings(session)


@router.get("/audit", response_model=Page[AuditOut])
async def list_audit(
    session: SessionDep, _: AdminUser, limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0), action: str | None = None,
):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    res = await session.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))
    items = [
        AuditOut(
            id=a.id, actor_user_id=a.actor_user_id, project_id=a.project_id, action=a.action,
            subject_type=a.subject_type, subject_id=a.subject_id, before=a.before, after=a.after,
            created_at=a.created_at.isoformat(),
        )
        for a in res.scalars()
    ]
    return Page(items=items, total=total)


@router.get("/jobs", response_model=Page[JobOut])
async def list_jobs(
    session: SessionDep, _: AdminUser, status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
):
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    res = await session.execute(stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset))
    items = [
        JobOut(
            id=j.id, type=j.type, status=j.status, progress=j.progress, message=j.message,
            error=j.error, project_id=j.project_id, user_id=j.user_id,
            created_at=j.created_at.isoformat(),
            finished_at=j.finished_at.isoformat() if j.finished_at else None,
        )
        for j in res.scalars()
    ]
    return Page(items=items, total=total)
